"""강의자료 실시간 AI 필기 서버 (MVP)."""

import asyncio
import contextlib
import datetime
import hashlib
import json
import logging
import os
import re
import time
from urllib.parse import quote
from contextlib import asynccontextmanager

import anthropic
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import training_log
from .config import settings
from .db import Database
from .live_session import LiveSession
from .llm import LLMError, accept_fixed_speech, make_llm
from .beyond import beyond_slides
from .study import cloze_items, fallback_mindmap, page_material, terms_of, tutor_context
from .exam_map import score_pages, top_pages
from .review import GRADES, NEW_PER_DAY, build_jokbo, card_key, schedule
from .semester import anki_text, concept_map, exam_plan, semester_context, session_markdown
from .notes_pdf import build_notes_pdf
from .quick_notes import EXAM_TALK
from .note_review import review_session
from .story import build_story, build_streak, wave as build_wave
from .recording import audio_file, recorded_ms, wav_parts
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
    app.state.ocr_jobs = {}
    app.state.transcriber = make_transcriber()
    app.state.progress = {}  # 세션 id → 녹음 파일 받아쓰기 진행률 (0~1)
    app.state.reviews = {}   # 세션 id → 강의 뒤 필기 다시 확인 결과 (몇 개 고쳤는지)
    app.state.notes_pdf = {}  # 세션 id → 정리 PDF 만들기 상태
    app.state.exam_jobs = {}  # 강의자료 id → 예상 문제 만들기 상태
    app.state.study_jobs = {}  # (세션 id, 종류) → 공부 도구 만들기 상태
    warm_up = getattr(app.state.llm, "warm_up", None)
    if warm_up:
        asyncio.create_task(warm_up())
    yield


app = FastAPI(title="Lecture Notes MVP", lifespan=lifespan)


@app.middleware("http")
async def remember_session(request, call_next):
    """학습 데이터에 어느 강의의 요청인지 남기려고, /sessions/{id}/... 요청이면 강의 id를 기억해 둔다."""
    parts = request.url.path.split("/")
    if len(parts) > 2 and parts[1] == "sessions" and len(parts[2]) == 32:
        training_log.current_session.set(parts[2])
    return await call_next(request)


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
    # "맞아요": 확인 필요 필기가 맞다고 확인 (우리 AI 학습에 '확인된 정답'으로 들어간다)
    confirm: bool = False


@app.get("/health")
def health():
    model = {"ollama": settings.ollama_model, "claude": settings.annotation_model,
             "groq": settings.groq_model, "hybrid": f"{settings.groq_model} + {settings.ollama_model}"}.get(settings.llm_mode)
    return {"ok": True, "llm_mode": settings.llm_mode, "model": model, "stt_mode": settings.stt_mode}


# 강의자료


SLIDE_EXTENSIONS = (".ppt", ".pptx", ".key", ".odp", ".doc", ".docx", ".hwp", ".hwpx")


def _to_pdf(data: bytes, filename: str) -> bytes:
    """PPT·워드·한글 파일은 LibreOffice로 PDF로 바꾼다 (서버에 LibreOffice가 있을 때)."""
    import shutil
    import subprocess
    import tempfile

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise HTTPException(400, "이 서버에서는 PPT를 바로 바꿀 수 없어요. PowerPoint에서 'PDF로 저장'한 파일을 올려 주세요.")
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "slides" + os.path.splitext(filename)[1].lower())
        with open(src, "wb") as f:
            f.write(data)
        try:
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, src],
                           check=True, capture_output=True, timeout=180)
        except (subprocess.SubprocessError, OSError) as exc:
            raise HTTPException(400, "PPT를 PDF로 바꾸지 못했어요. 'PDF로 저장'한 파일을 올려 주세요.") from exc
        out = os.path.join(tmp, "slides.pdf")
        if not os.path.exists(out):
            raise HTTPException(400, "PPT를 PDF로 바꾸지 못했어요. 'PDF로 저장'한 파일을 올려 주세요.")
        return open(out, "rb").read()


SCANNED_CHARS = 15  # 쪽 글이 이보다 짧으면 그림(스캔)으로 된 쪽으로 본다


async def _read_scanned_pages(doc_id: str) -> None:
    """스캔본·그림 슬라이드: 글자가 없는 쪽을 그림으로 만들어 사진 읽는 AI로 글자를 읽고, 쪽 추적이 되게 쪽 글을 채운다."""
    import pymupdf

    path = _pdf_path(doc_id)
    pdf = pymupdf.open(path)
    pages = db().list_pages(doc_id)
    app.state.ocr_jobs[doc_id] = {"status": "reading", "done": 0, "total": sum(1 for p in pages if len((p["text"] or "").strip()) < SCANNED_CHARS)}
    try:
        for page in pages:
            if len((page["text"] or "").strip()) >= SCANNED_CHARS:
                continue
            image = pdf[page["page_no"] - 1].get_pixmap(dpi=110).tobytes("jpg", jpg_quality=80)
            try:
                read = await app.state.llm.read_board(image, "image/jpeg")
            except Exception:
                log.exception("%s쪽 글자 읽기 실패", page["page_no"])
                read = {}
            text = str(read.get("text", "")).strip()
            if text:
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:12]
                # 문단 위치는 모르므로 위에서부터 고르게 나눠 둔다 (형광펜은 대략의 줄에 붙는다)
                blocks = [{"x": 0.06, "y": 0.08 + i * 0.84 / max(1, len(lines)), "w": 0.88, "h": 0.84 / max(1, len(lines)) * 0.9, "text": ln}
                          for i, ln in enumerate(lines)]
                db().replace_blocks(page["id"], "\n".join(lines), blocks)
            app.state.ocr_jobs[doc_id]["done"] += 1
    finally:
        app.state.ocr_jobs[doc_id]["status"] = "done"


@app.get("/documents/{doc_id}/ocr")
def ocr_status(doc_id: str):
    return app.state.ocr_jobs.get(doc_id, {"status": "none", "done": 0, "total": 0})


@app.post("/documents")
async def upload_document(background: BackgroundTasks, file: UploadFile = File(...), title: str | None = Form(None),
                          course: str = Form("")):
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "파일은 50MB 이하만 올릴 수 있습니다.")
    if (file.filename or "").lower().endswith(SLIDE_EXTENSIONS):
        data = await asyncio.to_thread(_to_pdf, data, file.filename or "slides.pptx")
    try:
        pages = parse_pdf(data)
    except PDFParseError as exc:
        raise HTTPException(400, str(exc)) from exc
    name = title or os.path.splitext(file.filename or "강의자료")[0]
    doc_id = db().create_document(name, pages, extract_keywords(pages))
    if course.strip():
        db().set_course(doc_id, course.strip()[:40])
    # 웹앱은 기기에 PDF를 두지 않으므로 서버에 보관해 두고 다시 내려준다
    os.makedirs(settings.upload_dir, exist_ok=True)
    with open(_pdf_path(doc_id), "wb") as f:
        f.write(data)
    if any(len((p.get("text") or "").strip()) < SCANNED_CHARS for p in pages):
        background.add_task(_read_scanned_pages, doc_id)
    return db().get_document(doc_id)


class DocumentUpdate(BaseModel):
    title: str | None = None
    course: str | None = None


@app.patch("/documents/{doc_id}")
def update_document(doc_id: str, body: DocumentUpdate):
    if db().get_document(doc_id) is None:
        raise HTTPException(404, "강의자료가 없습니다.")
    if body.title is not None and body.title.strip():
        db().rename_document(doc_id, body.title.strip()[:80])
    if body.course is not None:
        db().set_course(doc_id, body.course.strip()[:40])
    return next(d for d in db().list_documents() if d["id"] == doc_id)


def _pdf_path(doc_id: str) -> str:
    return os.path.join(settings.upload_dir, f"{doc_id}.pdf")


@app.get("/documents/{doc_id}/pdf")
def get_document_pdf(doc_id: str):
    if db().get_document(doc_id) is None or not os.path.exists(_pdf_path(doc_id)):
        raise HTTPException(404, "강의자료 파일이 없습니다.")
    return FileResponse(_pdf_path(doc_id), media_type="application/pdf")


class NotebookRequest(BaseModel):
    title: str = ""
    course: str = ""
    kind: str = "notebook"  # notebook = 자료 없는 수업, meeting = 회의


@app.post("/documents/notebook")
def create_notebook(body: NotebookRequest):
    """강의자료 없는 수업(또는 회의): 빈 줄 노트로 시작한다. 주제가 바뀔 때마다 쪽이 늘고, 쪽마다 AI가 제목을 붙인다."""
    kind = "meeting" if body.kind == "meeting" else "notebook"
    title = body.title.strip() or time.strftime("%m월 %d일 회의" if kind == "meeting" else "%m월 %d일 수업")
    doc_id = db().create_notebook(title, kind)
    if body.course.strip():
        db().set_course(doc_id, body.course.strip()[:40])
    return db().get_document(doc_id)


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
            if any(name.startswith(sid) or name in (f"notes-{sid}.pdf", f"full-{sid}.wav") for sid in sessions):
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


@app.get("/sessions/{session_id}/glossary")
def get_glossary(session_id: str):
    """실시간 용어 사전: 강의 중에 처음 나온 전문용어와 뜻 (나온 순서대로)."""
    _session_or_404(session_id)
    return db().list_terms(session_id)


@app.get("/sessions/{session_id}/audio")
def get_session_audio(session_id: str):
    """강의 녹음 (필기를 누르면 그 순간부터 듣기). 구간 요청(Range)을 지원해 원하는 위치부터 재생된다."""
    _session_or_404(session_id)
    found = audio_file(session_id)
    if found is None:
        raise HTTPException(404, "이 강의는 서버에 녹음이 없어요.")
    path, media_type = found
    return FileResponse(path, media_type=media_type)


@app.get("/sessions/{session_id}/transcript")
def get_transcript(session_id: str):
    """받아쓰기 전체 (문장마다 시각과 추정 페이지)"""
    _session_or_404(session_id)
    return db().get_segments(session_id)


@app.get("/sessions/{session_id}/annotations")
def list_annotations(session_id: str):
    _session_or_404(session_id)
    photos = db().photo_by_annotation(session_id)
    return [{**a, "photo_id": photos.get(a["id"])} for a in db().list_annotations(session_id)]


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
    # 다시 연결할 때마다 녹음 파일을 새로 만들고(앞부분을 덮어쓰지 않게), 받아쓰기 시각은 앞 조각들 길이에 이어 매긴다
    parts = wav_parts(session_id)
    offset_ms = recorded_ms(session_id)
    os.makedirs(settings.upload_dir, exist_ok=True)
    wav_path = os.path.join(settings.upload_dir, f"{session_id}-{len(parts) + 1}.wav")
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                # 마이크 소리 (16kHz 16비트 모노 PCM): 서버에서 Whisper로 받아쓴다
                live.feed_audio(message["bytes"], app.state.transcriber, wav_path, offset_ms)
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


async def _refine_transcript(session_id: str, document_id: str) -> None:
    """폰이 받아쓴 강의(빠르지만 덜 정확)는 강의가 끝난 뒤 녹음을 더 큰 모델로 다시 받아써서 글을 바로잡는다.
    요약·퀴즈·정리·검색·다시 듣기가 이 정확한 글을 쓴다. 실패하면 폰이 받아쓴 글 그대로 둔다."""
    marker = os.path.join(settings.upload_dir, f"{session_id}.device")
    if not os.path.exists(marker):
        return
    try:
        audio = audio_file(session_id)
        old = db().get_segments(session_id)
        if not audio or not old:
            return
        doc = db().get_document(document_id)
        progress = app.state.progress
        segments = await asyncio.to_thread(
            app.state.transcriber.transcribe, audio[0], " ".join(doc["keywords"][:40]),
            lambda p: progress.__setitem__(session_id, p))
        # 다시 받아쓴 글이 너무 짧으면(녹음이 끊겼거나 받아쓰기 실패) 바꾸지 않는다
        if sum(len(s.text) for s in segments) >= 0.6 * sum(len(s["text"]) for s in old):
            n = db().refine_segments(session_id, [(s.start_ms, s.end_ms, s.text) for s in segments])
            log.info("다시 받아쓰기: 문장 %d개 → %d개", len(old), n)
        os.remove(marker)
    except Exception:
        log.exception("다시 받아쓰기 실패 (폰이 받아쓴 글을 그대로 씀)")
    finally:
        app.state.progress.pop(session_id, None)


async def _review_notes(session_id: str, document_id: str) -> None:
    """필기 두 번 쓰기: 강의 전체를 본 AI가 실시간 필기를 다시 확인해 바로잡는다 (app/note_review.py). 실패해도 필기는 그대로."""
    if not settings.review_notes:
        return
    try:
        doc = db().get_document(document_id)
        if doc.get("kind", "slides") != "slides":
            return  # 노트·회의는 쪽이 주제 단위라 옮길 곳이 다르다
        progress = app.state.progress
        done = await review_session(db(), app.state.llm, session_id, doc["pages"], set(db().photo_by_annotation(session_id)),
                                    lambda p: progress.__setitem__(session_id, p))
        if done["checked"]:
            log.info("필기 다시 확인: %s", done)
            app.state.reviews[session_id] = done
    except Exception:
        log.exception("필기 다시 확인 실패 (실시간 필기를 그대로 씀)")
    finally:
        app.state.progress.pop(session_id, None)


async def _summarize(session_id: str, document_id: str) -> None:
    await _refine_transcript(session_id, document_id)
    await _review_notes(session_id, document_id)
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
            "progress": app.state.progress.get(session_id), "review": app.state.reviews.get(session_id)}


# "방금 뭐라고?": 수업 중 질문. 최근 2분 설명과 지금 슬라이드를 근거로 답하고, 관련 문단 옆에 질문 포스트잇으로 붙인다

RECENT_SPEECH_MS = 120_000
QUICK_QUESTION = "방금 설명한 내용을 쉽게 다시 설명해 줘"


class AskRequest(BaseModel):
    question: str = ""
    page_no: int


@app.post("/sessions/{session_id}/ask")
async def ask(session_id: str, body: AskRequest):
    session = _session_or_404(session_id)
    doc = db().get_document(session["document_id"])
    page = next((p for p in doc["pages"] if p["page_no"] == body.page_no), None)
    if page is None:
        raise HTTPException(404, "그 페이지가 없습니다.")
    segments = db().get_segments(session_id)
    latest = max((s["start_ms"] for s in segments), default=0)
    recent = " ".join(s["text"] for s in segments if s["start_ms"] >= latest - RECENT_SPEECH_MS)
    question = body.question.strip() or QUICK_QUESTION
    try:
        result = await app.state.llm.ask(question, page, recent)
    except anthropic.RateLimitError as exc:
        raise HTTPException(429, "요청이 많아요. 잠시 뒤 다시 물어봐 주세요.") from exc
    except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError) as exc:
        log.exception("질문 답변 실패")
        raise HTTPException(502, f"답을 만들지 못했어요: {exc}") from exc
    answer = str(result.get("answer", "")).strip()
    if not answer:
        raise HTTPException(502, "답을 만들지 못했어요.")
    block_ids = {b["id"] for b in page["blocks"]}
    block_id = result.get("block_id") if result.get("block_id") in block_ids else None
    return db().add_annotation(session_id, page["id"], block_id, "qa", f"Q. {question}\nA. {answer}", latest)


# 딴생각 따라잡기: 최근 몇 분 동안의 설명을 몇 줄로


class CatchUpRequest(BaseModel):
    minutes: float = 3


@app.post("/sessions/{session_id}/catch-up")
async def catch_up(session_id: str, body: CatchUpRequest):
    session = _session_or_404(session_id)
    segments = db().get_segments(session_id)
    latest = max((s["end_ms"] for s in segments), default=0)
    since = latest - int(body.minutes * 60_000)
    missed = [s for s in segments if s["end_ms"] >= since]
    if not missed:
        return {"points": [], "pages": [], "from_ms": since, "to_ms": latest}
    page_nos = sorted({s["page_no"] for s in missed if s["page_no"]})
    texts = {p["page_no"]: p["text"] for p in db().list_pages(session["document_id"])}
    slides = [{"page_no": no, "text": texts.get(no, "")} for no in page_nos]
    try:
        points = await app.state.llm.catch_up(slides, " ".join(s["text"] for s in missed))
    except anthropic.RateLimitError as exc:
        raise HTTPException(429, "요청이 많아요. 잠시 뒤 다시 눌러 주세요.") from exc
    except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError) as exc:
        log.exception("따라잡기 실패")
        raise HTTPException(502, f"정리하지 못했어요: {exc}") from exc
    return {"points": points, "pages": page_nos, "from_ms": max(since, 0), "to_ms": latest}


# 교수님만 말한 내용: 슬라이드에 없는 설명의 비율과, 그런 설명을 담은 필기


@app.get("/sessions/{session_id}/beyond-slides")
def get_beyond_slides(session_id: str):
    session = _session_or_404(session_id)
    texts = {p["page_no"]: p["text"] for p in db().list_pages(session["document_id"])}
    return beyond_slides(texts, db().get_segments(session_id), db().list_annotations(session_id))


# 공부 도구 (유니브 AI처럼): 플래시카드 · 개념 메모 · 마인드맵 · 암기(빈칸) · AI 튜터

STUDY_AI_KINDS = ("flashcards", "concepts", "mindmap", "bilingual")


def _study_inputs(session_id: str) -> tuple[dict, list[dict], str]:
    session = _session_or_404(session_id)
    doc = db().get_document(session["document_id"])
    texts = {p["page_no"]: p["text"] for p in db().list_pages(doc["id"])}
    pages = [{**p, "text": texts.get(p["page_no"], "")} for p in doc["pages"]]
    material = page_material(pages, db().get_segments(session_id), db().list_annotations(session_id))
    digest = hashlib.sha256(json.dumps([[p["page_no"], p["speech"], [(n["type"], n["text"]) for n in p["notes"]]]
                                        for p in material], ensure_ascii=False).encode()).hexdigest()
    return doc, material, digest


async def _build_study(session_id: str, kind: str) -> None:
    job = app.state.study_jobs[(session_id, kind)]
    doc, material, digest = _study_inputs(session_id)
    try:
        if kind == "mindmap":
            summary = db().get_summary(session_id) or {}
            page_summaries = summary.get("pages") or [{"page_no": p["page_no"], "summary": (p["title"] + " " + p["speech"])[:200]}
                                                      for p in material]
            try:
                data = await app.state.llm.mindmap(doc["title"], page_summaries)
                body = {"label": str(data.get("root") or doc["title"]), "children": [
                    {"label": str(b.get("label", "")), "page_no": b.get("page_no"),
                     "children": [{"label": str(leaf)} for leaf in b.get("leaves", []) if str(leaf).strip()]}
                    for b in data.get("branches", []) if str(b.get("label", "")).strip()]}
                if not body["children"]:
                    raise LLMError("마인드맵 가지가 없습니다")
            except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError):
                log.exception("마인드맵 AI 실패, 규칙으로 만듭니다")
                body = fallback_mindmap(doc["title"], material)
        else:
            job["total"] = len(material)
            body = []
            for page in material:
                try:
                    # 쪽 자료는 slide에 슬라이드 글이 있다 (프롬프트는 page["text"]를 읽는다)
                    items = await app.state.llm.study_page(kind, {**page, "text": page["slide"]}, page["speech"], page["notes"])
                    body += [{**item, "page_no": page["page_no"]} for item in items]
                except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError):
                    log.exception("%s쪽 %s 만들기 실패", page["page_no"], kind)
                job["done"] += 1
        db().save_study(session_id, kind, digest, body)
    finally:
        app.state.study_jobs.pop((session_id, kind), None)


def _study_status(session_id: str, kind: str, digest: str) -> dict:
    job = app.state.study_jobs.get((session_id, kind))
    if job:
        return {**job, "body": None}
    saved = db().get_study(session_id, kind)
    if saved:
        return {"status": "ready", "done": 0, "total": 0, "body": saved[1], "stale": saved[0] != digest}
    return {"status": "none", "done": 0, "total": 0, "body": None}


@app.get("/sessions/{session_id}/study/{kind}")
def get_study(session_id: str, kind: str):
    doc, material, digest = _study_inputs(session_id)
    if kind == "cloze":
        # 암기: AI 없이 바로 만든다 (강의자료·노트 제목의 용어를 빈칸으로)
        vocabulary = [t for p in material for t in terms_of(p["slide"])] + (doc.get("keywords") or [])
        return {"status": "ready", "body": cloze_items(material, vocabulary)}
    if kind not in STUDY_AI_KINDS:
        raise HTTPException(404, "없는 공부 도구입니다.")
    return _study_status(session_id, kind, digest)


@app.post("/sessions/{session_id}/study/{kind}", status_code=202)
def start_study(session_id: str, kind: str, background: BackgroundTasks):
    if kind not in STUDY_AI_KINDS:
        raise HTTPException(404, "없는 공부 도구입니다.")
    _, material, digest = _study_inputs(session_id)
    if not material:
        raise HTTPException(400, "아직 강의 내용이 없어요.")
    if (session_id, kind) not in app.state.study_jobs:
        saved = db().get_study(session_id, kind)
        if saved and saved[0] == digest:
            return _study_status(session_id, kind, digest)
        app.state.study_jobs[(session_id, kind)] = {"status": "building", "done": 0, "total": 0}
        background.add_task(_build_study, session_id, kind)
    return _study_status(session_id, kind, digest)


class TutorMessage(BaseModel):
    role: str
    content: str


class TutorRequest(BaseModel):
    messages: list[TutorMessage]


@app.post("/sessions/{session_id}/tutor")
async def tutor(session_id: str, body: TutorRequest):
    """AI 튜터: 질문과 가까운 쪽들의 슬라이드·설명·필기를 근거로 답한다. 대화 기록은 앱이 들고 있다가 보낸다."""
    messages = [m.model_dump() for m in body.messages if m.content.strip()][-10:]
    if not messages or messages[-1]["role"] != "user":
        raise HTTPException(400, "질문이 없어요.")
    _, material, _ = _study_inputs(session_id)
    overview = (db().get_summary(session_id) or {}).get("overview", "")
    question = " ".join(m["content"] for m in messages if m["role"] == "user")[-500:]
    context, pages = tutor_context(material, question, overview)
    try:
        result = await app.state.llm.tutor(context, messages)
    except anthropic.RateLimitError as exc:
        raise HTTPException(429, "요청이 많아요. 잠시 뒤 다시 물어봐 주세요.") from exc
    except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError) as exc:
        log.exception("튜터 답변 실패")
        raise HTTPException(502, f"답을 만들지 못했어요: {exc}") from exc
    cited = [p for p in result.get("pages", []) if isinstance(p, int) and p in pages] or pages
    return {"answer": str(result.get("answer", "")).strip(), "pages": cited}


# 시험 예상 지도: 그 자료로 들은 모든 강의에서 페이지마다 시험에 나올 만한 정도(규칙) + 상위 페이지 예상 문제(AI)


def _exam_inputs(doc_id: str) -> tuple[dict, list[dict], list[dict]]:
    doc = db().get_document(doc_id)
    if doc is None:
        raise HTTPException(404, "강의자료가 없습니다.")
    texts = {p["page_no"]: p["text"] for p in db().list_pages(doc_id)}
    pages = [{**p, "text": texts.get(p["page_no"], "")} for p in doc["pages"]]
    sessions = [{"segments": db().get_segments(sid), "annotations": db().list_annotations(sid)}
                for sid in db().session_ids(doc_id)]
    return doc, pages, sessions


def _page_material(page_no: int, sessions: list[dict]) -> tuple[str, list[dict], str]:
    speech = " ".join(s["text"] for x in sessions for s in x["segments"] if s["page_no"] == page_no)
    notes = [a for x in sessions for a in x["annotations"] if a["page_no"] == page_no and not a["pending"]]
    digest = hashlib.sha256(json.dumps([speech, [(a["type"], a["text"]) for a in notes]],
                                       ensure_ascii=False).encode()).hexdigest()
    return speech, notes, digest


@app.get("/documents/{doc_id}/exam-map")
def exam_map(doc_id: str):
    doc, pages, sessions = _exam_inputs(doc_id)
    scores = score_pages([p["page_no"] for p in pages], sessions)
    questions = []
    for page_no in top_pages(scores):
        cached = db().get_exam_questions(doc_id, page_no)
        if cached:
            questions.append({"page_no": page_no, "questions": cached[1],
                              "stale": cached[0] != _page_material(page_no, sessions)[2]})
    job = app.state.exam_jobs.get(doc_id, {"status": "idle", "done": 0, "total": 0})
    return {"lectures": len(sessions), "pages": scores, "top": top_pages(scores), "questions": questions, "job": job}


async def _build_exam_questions(doc_id: str) -> None:
    job = app.state.exam_jobs[doc_id]
    _, pages, sessions = _exam_inputs(doc_id)
    by_no = {p["page_no"]: p for p in pages}
    todo = top_pages(score_pages(list(by_no), sessions))
    job["total"] = len(todo)
    for page_no in todo:
        speech, notes, digest = _page_material(page_no, sessions)
        cached = db().get_exam_questions(doc_id, page_no)
        if not cached or cached[0] != digest:
            try:
                questions = await app.state.llm.predict_questions(by_no[page_no], speech, notes)
                if questions:
                    db().save_exam_questions(doc_id, page_no, digest, questions)
            except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError):
                log.exception("%s쪽 예상 문제 만들기 실패", page_no)
        job["done"] += 1
    app.state.exam_jobs.pop(doc_id, None)


@app.post("/documents/{doc_id}/exam-questions", status_code=202)
def start_exam_questions(doc_id: str, background: BackgroundTasks):
    """점수가 높은 페이지(최대 3쪽)의 예상 문제를 만든다. 내용이 그대로인 페이지는 전에 만든 문제를 쓴다."""
    _exam_inputs(doc_id)
    if doc_id not in app.state.exam_jobs:
        app.state.exam_jobs[doc_id] = {"status": "building", "done": 0, "total": 0}
        background.add_task(_build_exam_questions, doc_id)
    return app.state.exam_jobs.get(doc_id, {"status": "idle", "done": 0, "total": 0})


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
        cached = db().get_page_notes(session_id, page["page_no"], digest)
        if cached is None:
            try:
                points = await app.state.llm.organize_page(page, speech, notes)
                if not EXAM_TALK.search(speech):
                    # 작은 모델은 시험 이야기가 없는 페이지에도 ★시험을 붙이곤 해서, 실제로 말한 페이지에만 남긴다
                    points = [re.sub(r"\s*\(★[^)]*\)", "", p) for p in points]
            except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError):
                # 한 페이지가 실패해도 PDF는 만든다 (그 페이지는 요약이나 받아쓰기만 들어간다)
                log.exception("%s쪽 정리 실패", page["page_no"])
                points = None
            fixed = await _fix_speech(page, speech)
            cached = {"points": points or [], "speech": fixed}
            if points is not None:
                db().save_page_notes(session_id, page["page_no"], digest, cached)
        organized.append({"page_no": page["page_no"], **cached})
        state["done"] += 1
    try:
        data = await asyncio.to_thread(
            build_notes_pdf, _pdf_path(doc["id"]), doc["title"], pages, annotations, segments,
            db().list_tasks(session_id), db().get_summary(session_id), {"pages": organized}, session["started_at"],
            beyond_slides(texts, segments, annotations), db().list_terms(session_id))
        os.makedirs(settings.upload_dir, exist_ok=True)
        with open(_notes_pdf_path(session_id), "wb") as f:
            f.write(data)
    except Exception:
        log.exception("정리 PDF 만들기 실패")
        state["status"] = "failed"
        return
    app.state.notes_pdf.pop(session_id, None)


async def _fix_speech(page: dict, speech: str) -> str | None:
    """잘못 들린 단어만 고친 받아쓰기 (Groq·Claude 모드). 원문을 다시 썼거나 실패하면 None (원문을 쓴다)."""
    fix = getattr(app.state.llm, "fix_speech", None)
    if fix is None:
        return None
    try:
        fixed = await fix(page, speech)
    except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError):
        log.exception("%s쪽 받아쓰기 교정 실패", page["page_no"])
        return None
    return fixed if fixed != speech and accept_fixed_speech(speech, fixed) else None


@app.post("/sessions/{session_id}/notes-pdf", status_code=202)
def start_notes_pdf(session_id: str, background: BackgroundTasks):
    """정리 PDF를 (다시) 만든다. 필기를 고친 뒤 다시 부르면 고친 내용으로 새로 만든다."""
    session = _session_or_404(session_id)
    doc = db().get_document(session["document_id"])
    if doc["kind"] != "notebook" and not os.path.exists(_pdf_path(session["document_id"])):
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
        db().set_confidence(ann_id, 1.0)
        annotation = db().get_annotation(ann_id)
    if body.confirm:
        annotation = db().confirm_annotation(ann_id)
    return annotation


# 전체 검색: 모든 강의의 필기·교수님 말·용어·슬라이드


@app.get("/search")
def search(q: str):
    q = q.strip()
    if len(q) < 2:
        return {"query": q, "results": []}
    return {"query": q, "results": db().search(q[:60])}


@app.delete("/annotations/{ann_id}", status_code=204)
def delete_annotation(ann_id: int):
    if not db().delete_annotation(ann_id):
        raise HTTPException(404, "필기가 없습니다.")


# 내 필기: 학생이 직접 쓴 필기 (AI 필기와 같은 자리에 붙고, "직접 씀"으로 표시된다)


class MyNote(BaseModel):
    page_no: int
    text: str
    type: str = "explanation"


@app.post("/sessions/{session_id}/annotations")
def add_my_note(session_id: str, body: MyNote):
    session = _session_or_404(session_id)
    doc = db().get_document(session["document_id"])
    page = next((p for p in doc["pages"] if p["page_no"] == body.page_no), None)
    if page is None:
        raise HTTPException(404, "그 페이지가 없습니다.")
    if not body.text.strip():
        raise HTTPException(400, "필기 내용이 비어 있어요.")
    kind = body.type if body.type in ("explanation", "example", "emphasis", "exam", "notice", "qa") else "explanation"
    at = max((s["end_ms"] for s in db().get_segments(session_id)), default=0)
    note = db().add_annotation(session_id, page["id"], None, kind, body.text.strip()[:1000], at)
    db().mark_user_annotation(note["id"])
    return db().get_annotation(note["id"])


# "모르겠다": 수업 중 한 번 누르면 그 순간을 표시만 하고(수업 흐름을 끊지 않게), 설명은 나중에 만든다

CONFUSED_BEFORE_MS, CONFUSED_AFTER_MS = 90_000, 30_000
CONFUSED_QUESTION = "이 부분을 잘 모르겠어요. 핵심만 쉽게 다시 설명해 주세요."


class ConfusedRequest(BaseModel):
    page_no: int


@app.post("/sessions/{session_id}/confused")
def mark_confused(session_id: str, body: ConfusedRequest):
    _session_or_404(session_id)
    segments = db().get_segments(session_id)
    at = max((s["end_ms"] for s in segments), default=0)
    speech = " ".join(s["text"] for s in segments if s["end_ms"] >= at - 60_000)
    return db().add_mark(session_id, body.page_no, at, speech[-600:])


@app.post("/sessions/{session_id}/star")
def star(session_id: str, body: ConfusedRequest):
    """⭐ 여기 중요: 방금 설명한 문장을 강조 필기로 붙인다 (시험 예상 지도·족보에도 '강조'로 들어간다)."""
    session = _session_or_404(session_id)
    doc = db().get_document(session["document_id"])
    page = next((p for p in doc["pages"] if p["page_no"] == body.page_no), None) or doc["pages"][0]
    segments = db().get_segments(session_id)
    at = max((s["end_ms"] for s in segments), default=0)
    recent = [s["text"] for s in segments if s["end_ms"] >= at - 20_000][-2:]
    text = "⭐ 중요 표시" + (f": {' '.join(recent)[:200]}" if recent else "")
    note = db().add_annotation(session_id, page["id"], None, "emphasis", text, at)
    db().mark_user_annotation(note["id"])
    return db().get_annotation(note["id"])


@app.get("/sessions/{session_id}/marks")
def list_marks(session_id: str):
    _session_or_404(session_id)
    return db().list_marks(session_id)


@app.post("/marks/{mark_id}/explain")
async def explain_mark(mark_id: int):
    mark = db().get_mark(mark_id)
    if mark is None:
        raise HTTPException(404, "표시가 없습니다.")
    session = db().get_session(mark["session_id"])
    doc = db().get_document(session["document_id"])
    page = next((p for p in doc["pages"] if p["page_no"] == mark["page_no"]), None) or doc["pages"][0]
    # 누른 뒤에 교수님이 이어서 한 설명까지 넣어야 무엇이 헷갈렸는지 알 수 있다
    speech = " ".join(s["text"] for s in db().get_segments(session["id"])
                      if mark["at_ms"] - CONFUSED_BEFORE_MS <= s["end_ms"] <= mark["at_ms"] + CONFUSED_AFTER_MS)
    try:
        result = await app.state.llm.ask(CONFUSED_QUESTION, page, speech or mark["speech"])
    except anthropic.RateLimitError as exc:
        raise HTTPException(429, "요청이 많아요. 잠시 뒤 다시 시도해 주세요.") from exc
    except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError) as exc:
        log.exception("모르겠다 설명 실패")
        raise HTTPException(502, f"설명을 만들지 못했어요: {exc}") from exc
    answer = str(result.get("answer", "")).strip()
    if not answer:
        raise HTTPException(502, "설명을 만들지 못했어요.")
    return db().set_mark_explanation(mark_id, answer)


@app.delete("/marks/{mark_id}", status_code=204)
def delete_mark(mark_id: int):
    if not db().delete_mark(mark_id):
        raise HTTPException(404, "표시가 없습니다.")


# 족보 노트: 한 강의자료의 모든 강의에서 시험에 필요한 것만 모은 한 장 (AI 없이 이미 만든 것을 모은다)


@app.get("/documents/{doc_id}/jokbo")
def jokbo(doc_id: str):
    doc, pages, exam_sessions = _exam_inputs(doc_id)
    scores = score_pages([p["page_no"] for p in pages], exam_sessions)
    top = top_pages(scores, limit=5)
    questions = []
    for p in pages:
        cached = db().get_exam_questions(doc_id, p["page_no"])
        if cached:
            questions.append({"page_no": p["page_no"], "questions": cached[1]})
    sessions = []
    for sid, material in zip(db().session_ids(doc_id), exam_sessions):
        sessions.append({"id": sid, "annotations": material["annotations"], "terms": db().list_terms(sid),
                         "marks": db().list_marks(sid), "summary": db().get_summary(sid)})
    return build_jokbo({**doc, "pages": pages}, sessions, scores, top, questions, db().list_shared(doc_id))


# 망각 곡선 복습: 플래시카드·예상 문제·"모르겠다" 설명을 카드로 모아, 틀린 것은 자주 아는 것은 드물게


def _sync_cards(doc_id: str) -> None:
    for sid in db().session_ids(doc_id):
        saved = db().get_study(sid, "flashcards")
        for card in (saved[1] if saved else []) or []:
            front, back = str(card.get("front", "")).strip(), str(card.get("back", "")).strip()
            if front and back:
                db().upsert_card(card_key("flashcard", front), doc_id, "flashcard", front, back, card.get("page_no"))
        for mark in db().list_marks(sid):
            if mark["explanation"]:
                front = "헷갈렸던 부분: " + (mark["speech"][-120:] or f"{mark['page_no']}쪽")
                db().upsert_card(card_key("confused", str(mark["id"])), doc_id, "confused", front, mark["explanation"], mark["page_no"])
    for p in db().get_document(doc_id)["pages"]:
        cached = db().get_exam_questions(doc_id, p["page_no"])
        for q in (cached[1] if cached else []):
            if q.get("question") and q.get("answer"):
                db().upsert_card(card_key("exam", q["question"]), doc_id, "exam", q["question"], q["answer"], p["page_no"])


SOURCE_ORDER = {"confused": 0, "exam": 1, "flashcard": 2}


@app.get("/review/today")
def review_today(document_id: str | None = None):
    docs = [document_id] if document_id else [d["id"] for d in db().list_documents()]
    titles = {d["id"]: d["title"] for d in db().list_documents()}
    for doc_id in docs:
        if doc_id in titles:
            _sync_cards(doc_id)
    cards = [c for doc_id in docs for c in db().list_cards(doc_id)]
    now = time.time()
    due = sorted((c for c in cards if c["due_at"] is not None and c["due_at"] <= now), key=lambda c: (-c["lapses"], c["due_at"]))
    # 오늘 처음 본 카드 수만큼 새 카드를 덜 꺼낸다
    started_today = sum(1 for c in cards if c["last_at"] and c["reps"] <= 1 and c["lapses"] == 0 and now - c["last_at"] < 86400)
    fresh = sorted((c for c in cards if c["due_at"] is None), key=lambda c: (SOURCE_ORDER.get(c["source"], 9), c["created_at"]))
    fresh = fresh[:max(0, NEW_PER_DAY - started_today)]
    upcoming = min((c["due_at"] for c in cards if c["due_at"] and c["due_at"] > now), default=None)
    return {"cards": [{**c, "title": titles.get(c["document_id"], ""), "new": c["due_at"] is None} for c in due + fresh],
            "due": len(due), "new": len(fresh), "total": len(cards), "next_due_at": upcoming}


class ReviewAnswer(BaseModel):
    grade: str  # again | hard | good | easy


@app.post("/review/{key}")
def review_answer(key: str, body: ReviewAnswer):
    card = db().get_card(key)
    if card is None:
        raise HTTPException(404, "카드가 없습니다.")
    if body.grade not in GRADES:
        raise HTTPException(400, "grade는 again, hard, good, easy 중 하나입니다.")
    updated = schedule(card, GRADES[body.grade])
    db().save_card(updated)
    return updated


# 학기 전체: 개념 지도 · 학기 튜터


def _lectures() -> list[dict]:
    out = []
    for doc in db().list_documents():
        for s in doc["sessions"]:
            out.append({"doc_id": doc["id"], "doc_title": doc["title"], "session_id": s["id"], "started_at": s["started_at"]})
    return out


@app.get("/semester/concepts")
def semester_concepts():
    lectures = [{**lec, "terms": db().list_terms(lec["session_id"])} for lec in _lectures()]
    return concept_map(lectures)


@app.post("/semester/tutor")
async def semester_tutor(body: TutorRequest):
    """여러 강의를 넘나드는 질문 ("3주차랑 7주차 차이가 뭐야?"): 모든 강의의 쪽 중에서 가까운 것만 근거로"""
    messages = [m.model_dump() for m in body.messages if m.content.strip()][-10:]
    if not messages or messages[-1]["role"] != "user":
        raise HTTPException(400, "질문이 없어요.")
    chunks = []
    for lec in _lectures():
        _, material, _ = _study_inputs(lec["session_id"])
        chunks += [{**p, "doc_title": lec["doc_title"], "doc_id": lec["doc_id"], "session_id": lec["session_id"]} for p in material]
    if not chunks:
        raise HTTPException(400, "아직 강의 내용이 없어요.")
    question = " ".join(m["content"] for m in messages if m["role"] == "user")[-500:]
    context, chosen = semester_context(chunks, question)
    try:
        result = await app.state.llm.tutor(context, messages)
    except anthropic.RateLimitError as exc:
        raise HTTPException(429, "요청이 많아요. 잠시 뒤 다시 물어봐 주세요.") from exc
    except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError) as exc:
        log.exception("학기 튜터 답변 실패")
        raise HTTPException(502, f"답을 만들지 못했어요: {exc}") from exc
    cited = [p for p in result.get("pages", []) if isinstance(p, int) and 1 <= p <= len(chosen)] or list(range(1, len(chosen) + 1))
    sources = [{"doc_id": chosen[i - 1]["doc_id"], "doc_title": chosen[i - 1]["doc_title"], "session_id": chosen[i - 1]["session_id"],
                "page_no": chosen[i - 1]["page_no"]} for i in cited]
    return {"answer": str(result.get("answer", "")).strip(), "sources": sources}


# 시험 D-day


# 강의 스토리·수업 흐름·연속 공부: 규칙만으로 만든다 (AI 호출 없음 → 한도 없음)


@app.get("/sessions/{session_id}/story")
def session_story(session_id: str):
    session = _session_or_404(session_id)
    doc = db().get_document(session["document_id"])
    return build_story(doc["title"], session["started_at"], db().list_annotations(session_id), db().get_segments(session_id),
                       db().list_marks(session_id), db().list_tasks(session_id), db().list_terms(session_id),
                       db().get_summary(session_id))


@app.get("/waves")
def waves(document_id: str | None = None):
    """강의마다의 소리 무늬 (홈·강의 목록의 그림). 세션 id → {w, x}"""
    out = {}
    for d in db().list_documents():
        if document_id and d["id"] != document_id:
            continue
        for s in d["sessions"]:
            notes = [a for a in db().list_annotations(s["id"]) if not a["pending"]]
            out[s["id"]] = build_wave(notes, db().get_segments(s["id"]), db().list_marks(s["id"]))
    return out


@app.get("/streak")
def streak(tz: int = 540):
    stamps = [s["started_at"] for d in db().list_documents() for s in d["sessions"]]
    stamps += [c["last_at"] for d in db().list_documents() for c in db().list_cards(d["id"]) if c["last_at"]]
    return build_streak(stamps, max(-720, min(840, tz)), time.time())


# 시간표: 요일·시간에 맞춰 홈 화면이 "지금 수업"을 보여 주고, 그 과목 폴더로 바로 올리거나 녹음을 시작한다
# (지금이 몇 시인지는 폰이 안다: 서버는 저장만 한다)


class ClassCreate(BaseModel):
    course: str
    weekday: int = Field(ge=0, le=6)  # 0 = 월요일
    start: str  # HH:MM
    end: str
    place: str = ""


@app.get("/timetable")
def list_timetable():
    return db().list_classes()


@app.post("/timetable")
def add_timetable(body: ClassCreate):
    clock = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
    if not body.course.strip():
        raise HTTPException(400, "과목 이름을 적어 주세요.")
    if not clock.match(body.start) or not clock.match(body.end) or body.start >= body.end:
        raise HTTPException(400, "시간은 09:00 처럼 적고, 끝나는 시간이 시작보다 늦어야 해요.")
    return db().add_class(body.course.strip()[:40], body.weekday, body.start, body.end, body.place.strip()[:40])


@app.delete("/timetable/{class_id}", status_code=204)
def delete_timetable(class_id: int):
    if not db().delete_class(class_id):
        raise HTTPException(404, "없는 수업입니다.")


class ExamCreate(BaseModel):
    title: str
    exam_date: str  # YYYY-MM-DD
    doc_ids: list[str]


@app.get("/exams")
def list_exams():
    return db().list_exams()


@app.post("/exams")
def create_exam(body: ExamCreate):
    try:
        datetime.date.fromisoformat(body.exam_date)
    except ValueError as exc:
        raise HTTPException(400, "날짜는 YYYY-MM-DD 로 적어 주세요.") from exc
    known = {d["id"] for d in db().list_documents()}
    docs = [d for d in body.doc_ids if d in known]
    if not docs:
        raise HTTPException(400, "시험 범위 강의자료를 하나 이상 골라 주세요.")
    return db().add_exam(body.title.strip() or "시험", body.exam_date, docs)


@app.delete("/exams/{exam_id}", status_code=204)
def delete_exam(exam_id: int):
    if not db().delete_exam(exam_id):
        raise HTTPException(404, "시험이 없습니다.")


@app.get("/exams/{exam_id}/plan")
def get_exam_plan(exam_id: int, today: str | None = None):
    exam = db().get_exam(exam_id)
    if exam is None:
        raise HTTPException(404, "시험이 없습니다.")
    pages, confused_open = [], 0
    for doc_id in exam["doc_ids"]:
        if db().get_document(doc_id) is None:
            continue
        doc, doc_pages, sessions = _exam_inputs(doc_id)
        titles = {p["page_no"]: (p.get("text") or "").strip().split("\n")[0][:40] for p in doc_pages}
        for score in score_pages([p["page_no"] for p in doc_pages], sessions):
            pages.append({"doc_id": doc_id, "doc_title": doc["title"], "page_no": score["page_no"], "title": titles.get(score["page_no"], ""),
                          "score": score["score"], "reasons": score["reasons"]})
        confused_open += sum(1 for sid in db().session_ids(doc_id) for m in db().list_marks(sid) if not m["explanation"])
    pages.sort(key=lambda p: -p["score"])
    due = review_today(None)["cards"]
    due_cards = sum(1 for c in due if c["document_id"] in exam["doc_ids"])
    day = datetime.date.fromisoformat(today) if today else datetime.date.today()
    return {**exam_plan(exam["title"], exam["exam_date"], day, pages, due_cards, confused_open), "id": exam_id, "doc_ids": exam["doc_ids"]}


# 내보내기: Markdown(노션에 붙여 넣기) · Anki


@app.get("/sessions/{session_id}/export.md")
def export_markdown(session_id: str):
    session = _session_or_404(session_id)
    doc = db().get_document(session["document_id"])
    texts = {p["page_no"]: p["text"] for p in db().list_pages(doc["id"])}
    pages = [{**p, "text": texts.get(p["page_no"], "")} for p in doc["pages"]]
    text = session_markdown(doc, session["started_at"], pages, db().list_annotations(session_id), db().get_summary(session_id),
                            db().list_terms(session_id), db().list_tasks(session_id), db().list_marks(session_id))
    return Response(text, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(doc['title'])}.md"})


@app.get("/documents/{doc_id}/anki.txt")
def export_anki(doc_id: str):
    doc = db().get_document(doc_id)
    if doc is None:
        raise HTTPException(404, "강의자료가 없습니다.")
    _sync_cards(doc_id)
    cards = [(c["front"], c["back"], c["source"]) for c in db().list_cards(doc_id)]
    seen = set()
    for sid in db().session_ids(doc_id):
        for t in db().list_terms(sid):
            if t["term"] not in seen:
                seen.add(t["term"])
                cards.append((t["term"], t["definition"], "용어"))
    return Response(anki_text(doc["title"], cards), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(doc['title'])}-anki.txt"})


# 회의록: 회의 모드의 필기를 결정 · 할 일 · 미결 · 논의로 (AI 없이 모은다)


@app.get("/sessions/{session_id}/minutes")
def minutes(session_id: str):
    session = _session_or_404(session_id)
    doc = db().get_document(session["document_id"])
    texts = {p["page_no"]: p["text"] for p in db().list_pages(doc["id"])}
    notes = [a for a in db().list_annotations(session_id) if not a["pending"]]

    def pick(*kinds):
        return [{"page_no": a["page_no"], "text": a["text"]} for a in notes if a["type"] in kinds]

    tasks = db().list_tasks(session_id)
    actions = []
    for t in tasks:
        title = t["title"]
        owner = title[1:title.index("]")] if title.startswith("[") and "]" in title else "미정"
        actions.append({"id": t["id"], "owner": owner, "title": title.split("]", 1)[-1].strip() if "]" in title else title,
                        "due": t["due_text"], "detail": t["instructions"], "done": t["done"]})
    return {"title": doc["title"], "started_at": session["started_at"],
            "topics": [{"page_no": no, "title": texts.get(no) or f"{no}번 주제"} for no in sorted({a["page_no"] for a in notes})],
            "decisions": pick("emphasis"), "open": pick("qa"), "notices": pick("notice"),
            "discussion": pick("explanation", "example"), "actions": actions,
            "summary": (db().get_summary(session_id) or {}).get("overview", "")}


# 칠판·화이트보드 사진: 찍으면 AI가 읽어 지금 쪽에 필기로 붙인다 (읽지 못해도 사진은 필기로 남는다)

MAX_PHOTO_BYTES = 12 * 1024 * 1024


@app.post("/sessions/{session_id}/photo")
async def add_photo(session_id: str, page_no: int = Form(...), file: UploadFile = File(...)):
    session = _session_or_404(session_id)
    data = await file.read()
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "사진은 12MB 이하만 올릴 수 있어요.")
    mime = file.content_type if (file.content_type or "").startswith("image/") else "image/jpeg"
    doc = db().get_document(session["document_id"])
    page = next((p for p in doc["pages"] if p["page_no"] == page_no), None) or doc["pages"][0]
    os.makedirs(settings.upload_dir, exist_ok=True)
    path = os.path.join(settings.upload_dir, f"photo-{session_id}-{int(time.time() * 1000)}")
    with open(path, "wb") as f:
        f.write(data)
    photo_id = db().add_photo(session_id, page["page_no"], path, mime)
    try:
        read = await app.state.llm.read_board(data, mime)
        summary, text = str(read.get("summary", "")).strip(), str(read.get("text", "")).strip()
        note_text = f"칠판: {summary}" + (f"\n{text}" if text else "")
    except Exception:  # 사진을 읽는 모델이 없거나 실패해도 사진은 남긴다
        log.exception("칠판 사진 읽기 실패")
        note_text = "칠판 사진 (글을 읽지 못했어요)"
    segments = db().get_segments(session_id)
    at = max((s["end_ms"] for s in segments), default=0)
    note = db().add_annotation(session_id, page["id"], None, "example", note_text[:1500], at)
    db().link_photo(photo_id, note["id"])
    return {**note, "photo_id": photo_id}


@app.get("/photos/{photo_id}")
def get_photo(photo_id: int):
    photo = db().get_photo(photo_id)
    if photo is None or not os.path.exists(photo["path"]):
        raise HTTPException(404, "사진이 없습니다.")
    return FileResponse(photo["path"], media_type=photo["mime"])


# 영어 이중 노트: 받아쓰기가 영어인지 보고(앱이 탭을 보여 줄지 정한다), 쪽마다 원문·번역 짝은 공부 도구처럼 만든다


@app.get("/sessions/{session_id}/language")
def language(session_id: str):
    _session_or_404(session_id)
    text = " ".join(s["text"] for s in db().get_segments(session_id))
    letters = [c for c in text if c.isalpha()]
    latin = sum(1 for c in letters if c.isascii())
    ratio = latin / len(letters) if letters else 0.0
    return {"english_ratio": round(ratio, 3), "english": ratio >= 0.6}


# 함께 만드는 족보: 로그인 없이 파일로 주고받는다. 같은 강의자료(쪽 수·첫 쪽 글이 같은 것)끼리만 합친다


def _fingerprint(doc_id: str) -> str:
    pages = db().list_pages(doc_id)
    first = (pages[0]["text"] if pages else "")[:200]
    return hashlib.sha1(f"{len(pages)}\0{' '.join(first.split())}".encode()).hexdigest()[:16]


class ShareImport(BaseModel):
    nickname: str = ""
    share: dict


@app.get("/documents/{doc_id}/share")
def export_share(doc_id: str, nickname: str = ""):
    sheet = jokbo(doc_id)
    body = {k: sheet[k] for k in ("exam", "emphasis", "notice", "terms", "predicted")}
    body["confused"] = [c for c in sheet["confused"] if c["explanation"]]
    return {"format": "lecture-notes-share/1", "title": sheet["title"], "fingerprint": _fingerprint(doc_id),
            "nickname": nickname.strip()[:20], "created_at": time.time(), **body}


@app.post("/documents/{doc_id}/shared")
def import_share(doc_id: str, body: ShareImport):
    if db().get_document(doc_id) is None:
        raise HTTPException(404, "강의자료가 없습니다.")
    share = body.share
    if share.get("format") != "lecture-notes-share/1":
        raise HTTPException(400, "강의노트 족보 파일이 아니에요.")
    if share.get("fingerprint") != _fingerprint(doc_id):
        raise HTTPException(400, "다른 강의자료의 족보예요. 같은 PDF로 들은 친구의 파일만 합칠 수 있어요.")
    keep = {k: share.get(k, [])[:300] for k in ("exam", "emphasis", "notice", "terms", "predicted", "confused")}
    nickname = (body.nickname or share.get("nickname") or "친구").strip()[:20]
    return db().add_shared(doc_id, nickname, keep)


@app.get("/documents/{doc_id}/shared")
def list_shared(doc_id: str):
    return [{"id": s["id"], "nickname": s["nickname"], "created_at": s["created_at"],
             "counts": {k: len(v) for k, v in s["body"].items()}} for s in db().list_shared(doc_id)]


@app.delete("/shared/{shared_id}", status_code=204)
def delete_shared(shared_id: int):
    if not db().delete_shared(shared_id):
        raise HTTPException(404, "없는 족보 파일입니다.")


# 개인정보: 녹음·글이 어디로 가는지 그대로 알려 준다 (앱의 녹음 동의 화면이 이것을 보여 준다)


@app.get("/privacy")
def privacy():
    where = {"hybrid": "수업 중은 Groq (미국 클라우드), 강의 뒤 정리는 이 서버 안의 우리 AI (밖으로 안 나감)",
             "groq": "Groq (미국 클라우드, 무료 사용량)", "ollama": "이 서버 컴퓨터 안 (Ollama, 밖으로 안 나감)",
             "claude": "Anthropic Claude API (미국 클라우드)", "fake": "테스트용 가짜 응답 (밖으로 안 나감)"}
    stt = {"hybrid": "Groq Whisper (미국 클라우드), 한도에 걸리면 이 서버 안의 Whisper (밖으로 안 나감)",
           "groq": "Groq Whisper (미국 클라우드)", "whisper": "이 서버 컴퓨터 안 (Whisper, 밖으로 안 나감)", "fake": "테스트용"}
    return {"ai": where.get(settings.llm_mode, settings.llm_mode), "speech": stt.get(settings.stt_mode, settings.stt_mode),
            "storage": "녹음·필기·강의자료는 이 서버에만 저장돼요. 자료를 지우면 녹음과 필기도 함께 지워져요.",
            "training": settings.training_log}


# 웹앱 (iPhone Safari·안드로이드·PC 브라우저에서 바로 쓰는 버전). API 경로와 겹치지 않게 /app 아래에 둔다.
app.mount("/app", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="web")

# 새 프론트(web/, React). `cd web && npm run build`로 만든 결과가 있으면 /web 에서 보여 준다
WEB_DIST = os.path.join(os.path.dirname(__file__), "..", "..", "web", "dist")
if os.path.isdir(WEB_DIST):
    app.mount("/web", StaticFiles(directory=WEB_DIST, html=True), name="web-new")


@app.get("/", include_in_schema=False)
def root():
    # 새 프론트를 빌드해 두었으면 그쪽으로, 아니면 기존 웹앱으로
    return RedirectResponse("/web/" if os.path.isdir(WEB_DIST) else "/app/")
