"""강의자료 실시간 AI 필기 서버 (MVP)."""

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager

import anthropic
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import settings
from .db import Database
from .live_session import LiveSession
from .llm import LLMError, accept_fixed_speech, make_llm
from .beyond import beyond_slides
from .study import cloze_items, fallback_mindmap, page_material, terms_of, tutor_context
from .exam_map import score_pages, top_pages
from .notes_pdf import build_notes_pdf
from .quick_notes import EXAM_TALK
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
    app.state.transcriber = make_transcriber()
    app.state.progress = {}  # 세션 id → 녹음 파일 받아쓰기 진행률 (0~1)
    app.state.notes_pdf = {}  # 세션 id → 정리 PDF 만들기 상태
    app.state.exam_jobs = {}  # 강의자료 id → 예상 문제 만들기 상태
    app.state.study_jobs = {}  # (세션 id, 종류) → 공부 도구 만들기 상태
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
    model = {"ollama": settings.ollama_model, "claude": settings.annotation_model,
             "groq": settings.groq_model}.get(settings.llm_mode)
    return {"ok": True, "llm_mode": settings.llm_mode, "model": model, "stt_mode": settings.stt_mode}


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


class NotebookRequest(BaseModel):
    title: str = ""


@app.post("/documents/notebook")
def create_notebook(body: NotebookRequest):
    """강의자료 없는 수업: 빈 줄 노트로 시작한다. 교수님이 주제를 바꿀 때마다 쪽이 늘고, 쪽마다 AI가 제목을 붙인다."""
    title = body.title.strip() or time.strftime("%m월 %d일 수업")
    return db().get_document(db().create_notebook(title))


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

STUDY_AI_KINDS = ("flashcards", "concepts", "mindmap")


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
                    items = await app.state.llm.study_page(kind, page, page["speech"], page["notes"])
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
    return annotation


@app.delete("/annotations/{ann_id}", status_code=204)
def delete_annotation(ann_id: int):
    if not db().delete_annotation(ann_id):
        raise HTTPException(404, "필기가 없습니다.")


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
