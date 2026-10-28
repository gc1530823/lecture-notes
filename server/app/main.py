"""강의자료 실시간 AI 필기 서버 (MVP)."""

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
from contextlib import asynccontextmanager

import anthropic
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import settings
from .db import Database
from .live_session import LiveSession
from .llm import LLMError, make_llm
from .notes_pdf import build_notes_pdf
from .quick_notes import EXAM_TALK
from .pdf_parser import PDFParseError, extract_keywords, parse_pdf
from .stt import make_transcriber

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
TICK_SECONDS = 2.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = Database(settings.db_path)
    app.state.llm = make_llm()
    app.state.transcriber = make_transcriber()
    app.state.progress = {}  # 세션 id → 녹음 파일 받아쓰기 진행률 (0~1)
    app.state.notes_pdf = {}  # 세션 id → 정리 PDF 만들기 상태
    warm_up = getattr(app.state.llm, "warm_up", None)
    if warm_up:
        asyncio.create_task(warm_up())
    yield


app = FastAPI(title="Lecture Notes MVP", lifespan=lifespan)


def db() -> Database:
    return app.state.db


class SessionCreate(BaseModel):
    document_id: str


class TaskUpdate(BaseModel):
    done: bool


class AnnotationUpdate(BaseModel):
    text: str | None = None
    # 보류함의 필기를 붙일 페이지 (또는 다른 페이지로 옮길 때)
    page_no: int | None = None


@app.get("/health")
def health():
    model = {"ollama": settings.ollama_model, "claude": settings.annotation_model}.get(settings.llm_mode)
    return {"ok": True, "llm_mode": settings.llm_mode, "model": model}


# 강의자료


@app.post("/documents")
async def upload_document(file: UploadFile = File(...), title: str | None = Form(None)):
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "파일은 50MB 이하만 올릴 수 있습니다.")
    try:
        pages = parse_pdf(data)
    except PDFParseError as exc:
        raise HTTPException(400, str(exc)) from exc
    name = title or os.path.splitext(file.filename or "강의자료")[0]
    doc_id = db().create_document(name, pages, extract_keywords(pages))
    # 웹앱은 기기에 PDF를 두지 않으므로 서버에 보관해 두고 다시 내려준다
    os.makedirs(settings.upload_dir, exist_ok=True)
    with open(_pdf_path(doc_id), "wb") as f:
        f.write(data)
    return db().get_document(doc_id)


def _pdf_path(doc_id: str) -> str:
    return os.path.join(settings.upload_dir, f"{doc_id}.pdf")


@app.get("/documents/{doc_id}/pdf")
def get_document_pdf(doc_id: str):
    if db().get_document(doc_id) is None or not os.path.exists(_pdf_path(doc_id)):
        raise HTTPException(404, "강의자료 파일이 없습니다.")
    return FileResponse(_pdf_path(doc_id), media_type="application/pdf")


@app.get("/documents")
def list_documents():
    """서버에 저장된 강의자료와 강의 목록. 웹앱은 기기가 바뀌거나 브라우저 기록을 지워도 이 목록을 다시 받는다."""
    return db().list_documents()


@app.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str):
    if db().get_document(doc_id) is None:
        raise HTTPException(404, "강의자료가 없습니다.")
    sessions = db().delete_document(doc_id)
    with contextlib.suppress(FileNotFoundError):
        os.remove(_pdf_path(doc_id))
    # 그 강의들의 녹음(session-n.wav, session.m4a 등)과 정리 PDF도 지운다
    if os.path.isdir(settings.upload_dir):
        for name in os.listdir(settings.upload_dir):
            if any(name.startswith(sid) or name == f"notes-{sid}.pdf" for sid in sessions):
                with contextlib.suppress(FileNotFoundError):
                    os.remove(os.path.join(settings.upload_dir, name))


@app.get("/documents/{doc_id}")
def get_document(doc_id: str):
    doc = db().get_document(doc_id)
    if doc is None:
        raise HTTPException(404, "강의자료가 없습니다.")
    return doc


# 강의 세션


@app.post("/sessions")
def create_session(body: SessionCreate):
    if db().get_document(body.document_id) is None:
        raise HTTPException(404, "강의자료가 없습니다.")
    session_id = db().create_session(body.document_id)
    return db().get_session(session_id)


def _session_or_404(session_id: str) -> dict:
    session = db().get_session(session_id)
    if session is None:
        raise HTTPException(404, "강의 세션이 없습니다.")
    return session


MAX_AUDIO_BYTES = 500 * 1024 * 1024


@app.post("/sessions/from-audio")
async def session_from_audio(background: BackgroundTasks, document_id: str = Form(...), file: UploadFile = File(...)):
    """'음성 메모' 등으로 녹음해 둔 파일로 강의를 정리한다: 받아쓰기 → 페이지 추적·필기·과제 → 요약·퀴즈."""
    if db().get_document(document_id) is None:
        raise HTTPException(404, "강의자료가 없습니다.")
    session_id = db().create_session(document_id)
    os.makedirs(settings.upload_dir, exist_ok=True)
    path = os.path.join(settings.upload_dir, f"{session_id}.audio")
    size = 0
    with open(path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_AUDIO_BYTES:
                f.close()
                os.remove(path)
                raise HTTPException(413, "녹음 파일은 500MB 이하만 올릴 수 있습니다.")
            f.write(chunk)
    db().set_session_status(session_id, "transcribing")
    background.add_task(_process_audio, session_id, document_id, path)
    return db().get_session(session_id)


async def _process_audio(session_id: str, document_id: str, path: str) -> None:
    doc = db().get_document(document_id)
    progress = app.state.progress
    progress[session_id] = 0.0
    try:
        segments = await asyncio.to_thread(
            app.state.transcriber.transcribe, path, " ".join(doc["keywords"][:40]),
            lambda p: progress.__setitem__(session_id, p),
        )
    except Exception:  # 디코딩 실패, 모델 다운로드 실패 등
        log.exception("녹음 파일 받아쓰기 실패")
        db().set_session_status(session_id, "failed")
        return
    finally:
        progress.pop(session_id, None)

    async def discard(_message: dict) -> None:
        pass

    # 실시간 강의와 같은 파이프라인에 받아쓰기를 차례로 흘려 넣는다
    live = LiveSession(db(), app.state.llm, db().get_session(session_id), discard)
    for seg in segments:
        await live.handle({"type": "transcript_final", "text": seg.text, "start_ms": seg.start_ms, "end_ms": seg.end_ms})
    await live.close()
    db().set_session_status(session_id, "processing")
    await _summarize(session_id, document_id)


@app.get("/sessions/{session_id}/transcript")
def get_transcript(session_id: str):
    """받아쓰기 전체 (문장마다 시각과 추정 페이지)"""
    _session_or_404(session_id)
    return db().get_segments(session_id)


@app.get("/sessions/{session_id}/annotations")
def list_annotations(session_id: str):
    _session_or_404(session_id)
    return db().list_annotations(session_id)


@app.websocket("/sessions/{session_id}/stream")
async def stream(ws: WebSocket, session_id: str):
    session = db().get_session(session_id)
    if session is None:
        await ws.close(code=4404)
        return
    await ws.accept()

    async def send(message: dict) -> None:
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await ws.send_json(message)

    live = LiveSession(db(), app.state.llm, session, send)

    async def ticker():
        while True:
            await asyncio.sleep(TICK_SECONDS)
            await live.tick()

    tick_task = asyncio.create_task(ticker())
    # 다시 연결할 때마다 녹음 파일을 새로 만든다 (앞부분을 덮어쓰지 않게)
    part = len([n for n in os.listdir(settings.upload_dir) if n.startswith(session_id)]) \
        if os.path.isdir(settings.upload_dir) else 0
    os.makedirs(settings.upload_dir, exist_ok=True)
    wav_path = os.path.join(settings.upload_dir, f"{session_id}-{part + 1}.wav")
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                # 마이크 소리 (16kHz 16비트 모노 PCM): 서버에서 Whisper로 받아쓴다
                live.feed_audio(message["bytes"], app.state.transcriber, wav_path)
                continue
            try:
                payload = json.loads(message.get("text") or "")
            except json.JSONDecodeError:
                await send({"type": "error", "message": "JSON 형식이 아닙니다."})
                continue
            await live.handle(payload)
    except WebSocketDisconnect:
        pass
    finally:
        tick_task.cancel()
        await live.close()


@app.post("/sessions/{session_id}/end")
def end_session(session_id: str, background: BackgroundTasks):
    session = _session_or_404(session_id)
    if session["status"] == "recording":
        db().set_session_status(session_id, "processing")
        background.add_task(_summarize, session_id, session["document_id"])
    return db().get_session(session_id)


async def _summarize(session_id: str, document_id: str) -> None:
    pages = db().list_pages(document_id)
    try:
        body = await app.state.llm.summarize(pages, db().get_segments(session_id), db().list_annotations(session_id))
    except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError):
        log.exception("요약·퀴즈 생성 실패")
        db().set_session_status(session_id, "failed")
        return
    body["quiz"] = [q for q in body["quiz"] if 0 <= q["answer_index"] < len(q["choices"])]
    body["tips"] = []
    if settings.enable_web_tips:
        try:
            body["tips"] = await app.state.llm.research_tips(body)
        except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError):
            # 추가 자료는 덤이므로 실패해도 요약·퀴즈는 저장한다
            log.exception("추가 자료 검색 실패")
    db().save_summary(session_id, body)
    db().set_session_status(session_id, "done")


@app.get("/sessions/{session_id}/summary")
def get_summary(session_id: str):
    session = _session_or_404(session_id)
    return {"status": session["status"], "summary": db().get_summary(session_id),
            "progress": app.state.progress.get(session_id)}


# 강의 정리 PDF: 필기가 붙은 슬라이드 + AI가 쓴 페이지별 전체 정리 + 받아쓰기 + 과제


def _notes_pdf_path(session_id: str) -> str:
    return os.path.join(settings.upload_dir, f"notes-{session_id}.pdf")


def _notes_pdf_status(session_id: str) -> dict:
    state = app.state.notes_pdf.get(session_id)
    if state is not None:
        return state
    return {"status": "ready" if os.path.exists(_notes_pdf_path(session_id)) else "none", "done": 0, "total": 0}


async def _build_notes_pdf(session_id: str) -> None:
    state = app.state.notes_pdf[session_id]
    session = db().get_session(session_id)
    doc = db().get_document(session["document_id"])
    texts = {p["page_no"]: p["text"] for p in db().list_pages(doc["id"])}
    pages = [{**p, "text": texts.get(p["page_no"], "")} for p in doc["pages"]]
    segments = db().get_segments(session_id)
    annotations = db().list_annotations(session_id)
    todo = [p for p in pages if any(s["page_no"] == p["page_no"] for s in segments)]
    state["total"] = len(todo)
    organized = []
    for page in todo:
        speech = " ".join(s["text"] for s in segments if s["page_no"] == page["page_no"])
        notes = [a for a in annotations if a["page_no"] == page["page_no"] and not a["pending"]]
        digest = hashlib.sha256(json.dumps([speech, [(a["type"], a["text"]) for a in notes]],
                                           ensure_ascii=False).encode()).hexdigest()
        points = db().get_page_notes(session_id, page["page_no"], digest)
        if points is None:
            try:
                points = await app.state.llm.organize_page(page, speech, notes)
                if not EXAM_TALK.search(speech):
                    # 작은 모델은 시험 이야기가 없는 페이지에도 ★시험을 붙이곤 해서, 실제로 말한 페이지에만 남긴다
                    points = [re.sub(r"\s*\(★[^)]*\)", "", p) for p in points]
                db().save_page_notes(session_id, page["page_no"], digest, points)
            except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError):
                # 한 페이지가 실패해도 PDF는 만든다 (그 페이지는 요약이나 받아쓰기만 들어간다)
                log.exception("%s쪽 정리 실패", page["page_no"])
                points = []
        organized.append({"page_no": page["page_no"], "points": points})
        state["done"] += 1
    try:
        data = await asyncio.to_thread(
            build_notes_pdf, _pdf_path(doc["id"]), doc["title"], pages, annotations, segments,
            db().list_tasks(session_id), db().get_summary(session_id), {"pages": organized}, session["started_at"])
        os.makedirs(settings.upload_dir, exist_ok=True)
        with open(_notes_pdf_path(session_id), "wb") as f:
            f.write(data)
    except Exception:
        log.exception("정리 PDF 만들기 실패")
        state["status"] = "failed"
        return
    app.state.notes_pdf.pop(session_id, None)


@app.post("/sessions/{session_id}/notes-pdf", status_code=202)
def start_notes_pdf(session_id: str, background: BackgroundTasks):
    """정리 PDF를 (다시) 만든다. 필기를 고친 뒤 다시 부르면 고친 내용으로 새로 만든다."""
    session = _session_or_404(session_id)
    if not os.path.exists(_pdf_path(session["document_id"])):
        raise HTTPException(404, "강의자료 파일이 없습니다.")
    if _notes_pdf_status(session_id)["status"] != "building":
        app.state.notes_pdf[session_id] = {"status": "building", "done": 0, "total": 0}
        background.add_task(_build_notes_pdf, session_id)
    return _notes_pdf_status(session_id)


@app.get("/sessions/{session_id}/notes-pdf/status")
def notes_pdf_status(session_id: str):
    _session_or_404(session_id)
    return _notes_pdf_status(session_id)


@app.get("/sessions/{session_id}/notes-pdf")
def get_notes_pdf(session_id: str):
    session = _session_or_404(session_id)
    if not os.path.exists(_notes_pdf_path(session_id)):
        raise HTTPException(404, "정리 PDF가 아직 없습니다.")
    title = db().get_document(session["document_id"])["title"]
    return FileResponse(_notes_pdf_path(session_id), media_type="application/pdf", filename=f"{title} 정리.pdf")


# 수업 중에 받은 과제


@app.get("/sessions/{session_id}/tasks")
def list_tasks(session_id: str):
    _session_or_404(session_id)
    return db().list_tasks(session_id)


def _task_or_404(task_id: int) -> dict:
    task = db().get_task(task_id)
    if task is None:
        raise HTTPException(404, "과제가 없습니다.")
    return task


@app.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskUpdate):
    _task_or_404(task_id)
    return db().set_task_done(task_id, body.done)


@app.post("/tasks/{task_id}/draft")
async def draft_task(task_id: int):
    """지금까지의 강의 내용을 근거로 과제의 체크리스트·개요·초안을 만든다."""
    task = _task_or_404(task_id)
    session = db().get_session(task["session_id"])
    try:
        draft = await app.state.llm.draft_task(task, db().list_pages(session["document_id"]),
                                               db().get_segments(session["id"]), db().list_annotations(session["id"]))
    except anthropic.RateLimitError as exc:
        raise HTTPException(429, "요청이 많아요. 잠시 뒤 다시 시도해 주세요.") from exc
    except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError) as exc:
        log.exception("과제 초안 생성 실패")
        raise HTTPException(502, f"초안을 만들지 못했어요: {exc}") from exc
    return db().save_task_draft(task_id, draft)


# 필기 편집


@app.patch("/annotations/{ann_id}")
def update_annotation(ann_id: int, body: AnnotationUpdate):
    annotation = db().get_annotation(ann_id)
    if annotation is None:
        raise HTTPException(404, "필기가 없습니다.")
    if body.page_no is not None:
        session = db().get_session(annotation["session_id"])
        page = db().get_page(session["document_id"], body.page_no)
        if page is None:
            raise HTTPException(400, f"{body.page_no}페이지가 없습니다.")
        annotation = db().move_annotation(ann_id, page["id"])
    if body.text is not None and body.text.strip():
        annotation = db().update_annotation(ann_id, body.text.strip())
    return annotation


@app.delete("/annotations/{ann_id}", status_code=204)
def delete_annotation(ann_id: int):
    if not db().delete_annotation(ann_id):
        raise HTTPException(404, "필기가 없습니다.")


# 웹앱 (iPhone Safari·안드로이드·PC 브라우저에서 바로 쓰는 버전). API 경로와 겹치지 않게 /app 아래에 둔다.
app.mount("/app", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="web")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/app/")
