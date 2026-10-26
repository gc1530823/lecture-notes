"""강의자료 실시간 AI 필기 서버 (MVP)."""

import asyncio
import contextlib
import json
import logging
import os
from contextlib import asynccontextmanager

import anthropic
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .config import settings
from .db import Database
from .live_session import LiveSession
from .llm import LLMError, make_llm
from .pdf_parser import PDFParseError, extract_keywords, parse_pdf

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
TICK_SECONDS = 2.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = Database(settings.db_path)
    app.state.llm = make_llm()
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
    return db().get_document(doc_id)


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
    try:
        while True:
            raw = await ws.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await send({"type": "error", "message": "JSON 형식이 아닙니다."})
                continue
            await live.handle(message)
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
    return {"status": session["status"], "summary": db().get_summary(session_id)}


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
