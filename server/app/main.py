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
    yield


app = FastAPI(title="Lecture Notes MVP", lifespan=lifespan)


def db() -> Database:
    return app.state.db


class SessionCreate(BaseModel):
    document_id: str


class AnnotationUpdate(BaseModel):
    text: str


@app.get("/health")
def health():
    return {"ok": True, "llm_mode": settings.llm_mode}


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
    doc = db().get_document(document_id)
    pages = [db().get_page(document_id, p["page_no"]) for p in doc["pages"]]
    try:
        body = await app.state.llm.summarize(pages, db().get_segments(session_id), db().list_annotations(session_id))
    except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError):
        log.exception("요약·퀴즈 생성 실패")
        db().set_session_status(session_id, "failed")
        return
    body["quiz"] = [q for q in body["quiz"] if 0 <= q["answer_index"] < len(q["choices"])]
    db().save_summary(session_id, body)
    db().set_session_status(session_id, "done")


@app.get("/sessions/{session_id}/summary")
def get_summary(session_id: str):
    session = _session_or_404(session_id)
    return {"status": session["status"], "summary": db().get_summary(session_id)}


# 필기 편집


@app.patch("/annotations/{ann_id}")
def update_annotation(ann_id: int, body: AnnotationUpdate):
    annotation = db().update_annotation(ann_id, body.text.strip())
    if annotation is None:
        raise HTTPException(404, "필기가 없습니다.")
    return annotation


@app.delete("/annotations/{ann_id}", status_code=204)
def delete_annotation(ann_id: int):
    if not db().delete_annotation(ann_id):
        raise HTTPException(404, "필기가 없습니다.")
