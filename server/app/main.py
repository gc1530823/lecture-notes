"""강의자료 실시간 AI 필기 서버 (MVP)."""

import asyncio
import contextlib
import datetime
import hashlib
import json
import math
import logging
import os
import re
import secrets
import shutil
import time
from http.cookies import SimpleCookie
from urllib.parse import quote
from contextlib import asynccontextmanager

import anthropic
import pymupdf
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import a1retry, auth, backup, mailer, ocr, training_log
from .config import settings
from .db import Database
from .dedupe import merge_concepts
from .ocr import name_and_place, read_block
from .timetable_image import combine as combine_timetable, find_blocks, load_rgb
from .due import parse_due
from .live_session import LiveSession
from .llm import LLMError, accept_fixed_speech, clean_timetable, make_llm
from .beyond import beyond_slides
from .study import cloze_items, fallback_mindmap, page_material, terms_of, tutor_context
from .exam_map import score_pages, top_pages
from .review import GRADES, NEW_PER_DAY, build_jokbo, card_key, schedule
from .semester import anki_text, concept_map, exam_plan, semester_context, session_markdown
from .notes_pdf import build_notes_pdf
from .quick_notes import EXAM_TALK
from .note_review import review_session
from .ollama_llm import clean_quiz
from . import quiz as quizlib
from .story import build_exam_story, build_story, build_streak, wave as build_wave
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
    app.state.reviews = {}
    app.state.quiz_jobs = set()  # 퀴즈를 다시 내는 중인 강의   # 세션 id → 강의 뒤 필기 다시 확인 결과 (몇 개 고쳤는지)
    app.state.notes_pdf = {}
    app.state.study_pdf = {}  # 세션 id → AI 정리 노트 만들기 상태  # 세션 id → 정리 PDF 만들기 상태
    app.state.exam_jobs = {}  # 강의자료 id → 예상 문제 만들기 상태
    app.state.study_jobs = {}  # (세션 id, 종류) → 공부 도구 만들기 상태
    warm_up = getattr(app.state.llm, "warm_up", None)
    if warm_up:
        asyncio.create_task(warm_up())
    backups = asyncio.create_task(_backup_loop())
    a1 = asyncio.create_task(_a1_loop())
    yield
    backups.cancel()
    a1.cancel()


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


# 로그인과 사람별 공간 (INVITE_CODE 를 정했을 때만, app/auth.py)

class AuthGate:
    """서버 입구: 로그인한 사람을 CURRENT_USER 에 담고, 남의 자료 주소는 404 로 막는다 (HTTP·WebSocket 모두)"""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or not auth.enabled() or auth.is_public(scope["path"]):
            return await self.inner(scope, receive, send)
        user = None
        cookies = SimpleCookie()
        for key, value in scope.get("headers", []):
            if key == b"cookie":
                cookies.load(value.decode("latin-1"))
        token = cookies.get(auth.COOKIE)
        if token:
            user = app.state.db.login_user(auth.token_hash(token.value))
        if user is None:
            return await self._deny(scope, receive, send, 401, "로그인이 필요해요.")
        names_thing, owner = app.state.db.owner_of(scope["path"])
        if names_thing and owner is not None and owner != user["id"]:
            return await self._deny(scope, receive, send, 404, "없는 자료예요.")
        reset = auth.CURRENT_USER.set(user["id"])
        try:
            return await self.inner(scope, receive, send)
        finally:
            auth.CURRENT_USER.reset(reset)

    @staticmethod
    async def _deny(scope, receive, send, status: int, message: str):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401 if status == 401 else 4404})
            return
        await JSONResponse({"detail": message}, status_code=status)(scope, receive, send)


app.add_middleware(AuthGate)


class AuthRequest(BaseModel):
    name: str
    password: str
    invite: str = ""
    email: str = ""   # 가입할 때 (선택): 비밀번호를 잊었을 때 인증번호를 받는 곳


_login_fails: dict[str, list[float]] = {}


def _client(request: Request) -> str:
    """요청한 사람의 주소. Tailscale Funnel 은 이 컴퓨터 안(127.0.0.1)에서 넘겨주므로 그때만 X-Forwarded-For 를 믿는다"""
    host = request.client.host if request.client else "?"
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if host in ("127.0.0.1", "::1") and forwarded:
        return forwarded
    return request.headers.get("cf-connecting-ip") or host


def _too_many(request: Request, key: str = "", limit: int = 10, window: int = 600) -> bool:
    who = key + _client(request)
    recent = [t for t in _login_fails.get(who, []) if t > time.time() - window]
    _login_fails[who] = recent
    return len(recent) >= limit


ADMIN_LIMIT = (5, 900)          # 한 사람: 15분에 5번 틀리면 잠금
ADMIN_GLOBAL = (30, 3600)       # 모두 합쳐: 1시간에 30번 틀리면 관리자 로그인 전체 잠금 (주소를 바꿔 가며 시도해도)


def _start_login(request: Request, user: dict) -> JSONResponse:
    token = secrets.token_urlsafe(32)
    db().add_login(auth.token_hash(token), user["id"], time.time() + auth.LOGIN_DAYS * 86400)
    res = JSONResponse({"auth": True, "user": {"id": user["id"], "name": user["name"]}})
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    res.set_cookie(auth.COOKIE, token, max_age=auth.LOGIN_DAYS * 86400, httponly=True, samesite="lax", secure=secure, path="/")
    return res


@app.get("/auth/me")
def auth_me(request: Request):
    """로그인이 필요한 서버인지, 누가 로그인했는지 (웹앱이 처음에 묻는다)"""
    if not auth.enabled():
        return {"auth": False, "user": None}
    token = request.cookies.get(auth.COOKIE)
    user = db().login_user(auth.token_hash(token)) if token else None
    return {"auth": True, "user": {"id": user["id"], "name": user["name"]} if user else None}


@app.post("/auth/signup")
def auth_signup(body: AuthRequest, request: Request):
    if not auth.enabled():
        raise HTTPException(400, "이 서버는 로그인 없이 써요.")
    if _too_many(request):
        raise HTTPException(429, "잠시 뒤 다시 해 주세요.")
    name = body.name.strip()
    if not auth.invite_ok(body.invite, db().get_setting("invite_code")):
        _login_fails.setdefault(_client(request), []).append(time.time())
        raise HTTPException(403, "초대 코드가 맞지 않아요.")
    if not auth.NAME.match(name):
        raise HTTPException(400, "이름은 1~20자로 적어 주세요.")
    if len(body.password) < 6:
        raise HTTPException(400, "비밀번호는 6자 이상으로 해 주세요.")
    if db().user_by_name(name):
        raise HTTPException(409, "이미 있는 이름이에요. 다른 이름이나 로그인을 해 주세요.")
    email = body.email.strip()
    if email and not EMAIL_RE.match(email):
        raise HTTPException(400, "이메일 주소를 확인해 주세요.")
    if email and db().user_by_email(email):
        raise HTTPException(409, "다른 계정에 등록된 이메일이에요.")
    user = db().add_user(name, auth.hash_password(body.password))
    code = _new_code()   # 비밀번호를 잊었을 때 쓰는 복구 코드: 가입할 때 한 번 보여 준다
    db().set_recovery(user["id"], auth.hash_password(code))
    res = _start_login(request, user)
    body_json = json.loads(res.body)
    body_json["recovery_code"] = code
    if email:
        # 인증번호를 보내 확인받은 뒤에만 비밀번호 찾기에 쓴다 (주소를 잘못 적으면 남이 받게 되니까).
        # 메일 보내기가 아직 꺼져 있으면 주소만 남겨 두고, 나중에 설정에서 인증한다
        six = _six()
        db().set_email_code(user["id"], email, auth.hash_password(six), time.time() + 600)
        try:
            mailer.send(db(), email, "[LUNE] 이메일 인증번호",
                        f"LUNE 가입을 환영해요! 이메일 인증번호: {six}\n\n10분 안에 앱에 넣어 주세요. 직접 가입하지 않았다면 이 메일은 무시하세요.")
            body_json["email_status"] = "sent"
        except Exception:   # 메일 설정이 없거나 보내지 못함
            body_json["email_status"] = "pending"
    res.body = json.dumps(body_json, ensure_ascii=False).encode()
    res.headers["content-length"] = str(len(res.body))
    return res


@app.post("/auth/login")
def auth_login(body: AuthRequest, request: Request):
    if not auth.enabled():
        raise HTTPException(400, "이 서버는 로그인 없이 써요.")
    if _too_many(request):
        raise HTTPException(429, "여러 번 틀려서 10분 동안 막혔어요.")
    user = db().user_by_name(body.name.strip())
    if not user or not auth.check_password(body.password, user["password"]):
        _login_fails.setdefault(_client(request), []).append(time.time())
        raise HTTPException(401, "이름이나 비밀번호가 맞지 않아요.")
    return _start_login(request, user)


# 비밀번호 찾기 (이메일 없이): 복구 코드는 가입할 때 한 번 보여 주고(설정에서 다시 만들 수 있음),
# 그것도 잃어버린 친구에게는 서버 주인이 24시간 쓰는 초기화 코드를 내준다. 코드는 해시로만 저장한다.


def _new_code() -> str:
    abc = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(abc[b % len(abc)] for b in os.urandom(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def _norm_code(code: str) -> str:
    c = re.sub(r"[^A-Z0-9]", "", code.upper())
    if len(c) == 6 and c.isdigit():   # 메일로 받은 6자리 인증번호
        return c
    return f"{c[:4]}-{c[4:8]}-{c[8:]}"


class ResetRequest(BaseModel):
    name: str
    code: str
    password: str


class PasswordChange(BaseModel):
    current: str
    password: str


@app.post("/account/recovery-code")
def make_recovery_code():
    """복구 코드 새로 만들기 (로그인한 사람). 한 번만 보여 준다 — 예전 코드는 못 쓴다"""
    me = _me()
    code = _new_code()
    db().set_recovery(me, auth.hash_password(code))
    return {"code": code}


@app.get("/account/recovery")
def recovery_status():
    me = _me()
    return {"has_code": bool(db().recovery_info(me).get("recovery_hash"))}


@app.post("/auth/reset")
def reset_password(body: ResetRequest, request: Request):
    """비밀번호를 잊었을 때: 이름 + 복구 코드(또는 서버 주인의 초기화 코드) + 새 비밀번호 → 바꾸고 바로 로그인"""
    if not auth.enabled():
        raise HTTPException(400, "이 서버는 로그인 없이 써요.")
    if _too_many(request):
        raise HTTPException(429, "여러 번 틀려서 10분 동안 막혔어요.")
    who = body.name.strip()
    user = db().user_by_email(who) if "@" in who else db().user_by_name(who)   # 이름 또는 이메일
    info = db().recovery_info(user["id"]) if user else {}
    code = _norm_code(body.code)
    ok_recovery = bool(info.get("recovery_hash")) and auth.check_password(code, info["recovery_hash"])
    ok_reset = (bool(info.get("reset_hash")) and (info.get("reset_until") or 0) > time.time()
                and auth.check_password(code, info["reset_hash"]))
    if not user or not (ok_recovery or ok_reset):
        _login_fails.setdefault(_client(request), []).append(time.time())
        raise HTTPException(401, "이름이나 코드가 맞지 않아요.")
    if len(body.password) < 6:
        raise HTTPException(400, "새 비밀번호는 6자 이상으로 해 주세요.")
    db().set_password(user["id"], auth.hash_password(body.password))
    if ok_recovery:   # 복구 코드는 한 번 쓰면 끝 (설정에서 새로 만든다)
        db().set_recovery(user["id"], None)
    db().set_reset(user["id"], None, None)
    return _start_login(request, db().user_by_name(user["name"]))


@app.post("/account/password")
def change_password(body: PasswordChange, request: Request):
    """로그인한 채로 비밀번호 바꾸기 (지금 비밀번호 확인). 다른 기기 로그인은 끊기고 이 기기는 다시 로그인된다"""
    me = _me()
    user = db().user_by_name((db().get_user(me) or {}).get("name", ""))
    if not user or not auth.check_password(body.current, user["password"]):
        raise HTTPException(401, "지금 비밀번호가 맞지 않아요.")
    if len(body.password) < 6:
        raise HTTPException(400, "새 비밀번호는 6자 이상으로 해 주세요.")
    db().set_password(me, auth.hash_password(body.password))
    return _start_login(request, user)


EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")
_mail_sent: dict[str, list[float]] = {}


def _mail_ok(key: str) -> bool:
    """같은 사람·주소로 메일을 너무 자주 보내지 않게 (10분에 3번)"""
    recent = [t for t in _mail_sent.get(key, []) if t > time.time() - 600]
    _mail_sent[key] = recent
    if len(recent) >= 3:
        return False
    recent.append(time.time())
    return True


def _six() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


class EmailSet(BaseModel):
    email: str


class EmailVerify(BaseModel):
    code: str


@app.get("/account/email")
def my_email():
    me = _me()
    info = db().email_info(me)
    return {"email": info.get("email") or "", "pending": info.get("email_pending") or "", "mail_ready": mailer.account(db()) is not None}


@app.post("/account/email")
async def start_email(body: EmailSet):
    """이메일 등록: 그 주소로 6자리 인증번호를 보낸다 (10분)"""
    me = _me()
    email = body.email.strip()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "이메일 주소를 확인해 주세요.")
    other = db().user_by_email(email)
    if other and other["id"] != me:
        raise HTTPException(409, "다른 계정에 등록된 이메일이에요.")
    if not _mail_ok(me):
        raise HTTPException(429, "인증번호를 너무 자주 보냈어요. 10분 뒤 다시 해 주세요.")
    code = _six()
    db().set_email_code(me, email, auth.hash_password(code), time.time() + 600)
    try:
        await asyncio.to_thread(mailer.send, db(), email, "[LUNE] 이메일 인증번호",
                                f"LUNE 이메일 인증번호: {code}\n\n10분 안에 앱에 넣어 주세요. 직접 요청하지 않았다면 이 메일은 무시하세요.")
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"sent": email}


@app.post("/account/email/verify")
def verify_email(body: EmailVerify):
    me = _me()
    info = db().email_info(me)
    if not info.get("email_pending") or (info.get("email_code_until") or 0) < time.time() \
            or not auth.check_password(body.code.strip(), info.get("email_code_hash") or ""):
        raise HTTPException(400, "인증번호가 맞지 않거나 시간이 지났어요.")
    db().set_email(me, info["email_pending"])
    return my_email()


@app.delete("/account/email", status_code=204)
def remove_email():
    db().set_email(_me(), None)


class ForgotRequest(BaseModel):
    who: str   # 이름 또는 이메일


@app.post("/auth/forgot")
async def forgot_password(body: ForgotRequest, request: Request):
    """비밀번호 찾기: 이름이나 이메일로 → 등록·확인된 이메일로 6자리 인증번호 (10분). 계정이 있는지는 알려 주지 않는다"""
    if not auth.enabled():
        raise HTTPException(400, "이 서버는 로그인 없이 써요.")
    if _too_many(request):
        raise HTTPException(429, "여러 번 틀려서 10분 동안 막혔어요.")
    who = body.who.strip()
    user = db().user_by_email(who) if "@" in who else db().user_by_name(who)
    if mailer.account(db()) is None:
        raise HTTPException(503, "이 서버는 아직 메일을 보낼 수 없어요. 복구 코드로 하거나 서버 주인에게 초기화 코드를 받아 주세요.")
    if user and user.get("email") and _mail_ok("forgot:" + user["id"]):
        code = _six()
        db().set_reset(user["id"], auth.hash_password(code), time.time() + 600)
        try:
            await asyncio.to_thread(mailer.send, db(), user["email"], "[LUNE] 비밀번호 다시 만들기 인증번호",
                                    f"{user['name']}님의 LUNE 인증번호: {code}\n\n10분 안에 앱에 넣고 새 비밀번호를 정해 주세요.\n직접 요청하지 않았다면 이 메일은 무시하세요.")
        except RuntimeError:
            log.exception("비밀번호 찾기 메일 실패")
    return {"ok": True, "message": "등록된 이메일이 있으면 인증번호를 보냈어요. 메일함(스팸함도)을 확인해 주세요."}


class MailSetting(BaseModel):
    user: str
    password: str


@app.get("/admin/mail")
def mail_setting(request: Request):
    _admin(request)
    acc = mailer.account(db())
    return {"user": acc[0] if acc else ""}


@app.put("/admin/mail")
async def set_mail(body: MailSetting, request: Request):
    """관리자: 메일 보내기용 Gmail 계정 + 앱 비밀번호. 저장하기 전에 그 주소로 시험 메일을 보낸다"""
    _admin(request)
    if not EMAIL_RE.match(body.user.strip()):
        raise HTTPException(400, "Gmail 주소를 확인해 주세요.")
    old = (db().get_setting("smtp_user"), db().get_setting("smtp_password"))
    db().set_setting("smtp_user", body.user.strip())
    db().set_setting("smtp_password", body.password.strip())
    try:
        await asyncio.to_thread(mailer.send, db(), body.user.strip(), "[LUNE] 메일 보내기 설정 완료",
                                "이 메일이 왔다면 LUNE 이 비밀번호 찾기 인증번호를 보낼 수 있어요.")
    except RuntimeError as exc:
        db().set_setting("smtp_user", old[0])
        db().set_setting("smtp_password", old[1])
        raise HTTPException(400, str(exc)) from exc
    return {"user": body.user.strip()}


class ResetFor(BaseModel):
    name: str


@app.post("/admin/reset-code")
def issue_reset_code(body: ResetFor, request: Request):
    """관리자가 비밀번호를 잊은 사람에게 내주는 초기화 코드 (24시간)"""
    _admin(request)
    user = db().user_by_name(body.name.strip())
    if not user:
        raise HTTPException(404, "그 이름의 계정이 없어요.")
    code = _new_code()
    db().set_reset(user["id"], auth.hash_password(code), time.time() + 86400)
    return {"name": user["name"], "code": code, "until": time.time() + 86400}


@app.post("/auth/logout")
def auth_logout(request: Request):
    token = request.cookies.get(auth.COOKIE)
    if token:
        db().delete_login(auth.token_hash(token))
    res = JSONResponse({"ok": True})
    res.delete_cookie(auth.COOKIE, path="/")
    return res


class SessionCreate(BaseModel):
    document_id: str
    language: str = ""   # 'en' = 영어 강의 (처음에 체크), '' = 목소리로 정하기


class TaskUpdate(BaseModel):
    done: bool | None = None
    checked: bool | None = None   # 'AI가 찾음' 과제를 사람이 맞다고 확인
    title: str | None = None      # 과제 이름 고치기 (확인도 된다)
    due_on: str | None = None  # "YYYY-MM-DD", "" = 직접 정한 마감일 지우기


class AnnotationUpdate(BaseModel):
    text: str | None = None
    # 보류함의 필기를 붙일 페이지 (또는 다른 페이지로 옮길 때)
    page_no: int | None = None
    # "맞아요": 확인 필요 필기가 맞다고 확인 (우리 AI 학습에 '확인된 정답'으로 들어간다)
    confirm: bool = False
    # 필기 종류(색)를 사람이 바꿀 때
    type: str | None = None


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


def _same_document(data: bytes) -> dict | None:
    """이미 올린 강의자료 가운데 내용이 똑같은 파일"""
    digest = hashlib.sha256(data).digest()
    for doc in db().list_documents():
        path = _pdf_path(doc["id"])
        try:
            if os.path.getsize(path) != len(data):
                continue
            with open(path, "rb") as f:
                if hashlib.sha256(f.read()).digest() == digest:
                    return doc
        except OSError:
            continue
    return None


def _document_title(filename: str | None, pages: list[dict]) -> str:
    """자료 이름: 파일 이름. 파일 이름이 뜻 없는 것(너무 짧거나 숫자·기호뿐)이면 첫 쪽의 첫 줄(보통 강의 제목)"""
    stem = os.path.splitext(filename or "")[0].strip()
    if len(stem) >= 4 and re.search(r"[A-Za-z가-힣]{2,}", stem) and not re.fullmatch(r"(?i)(slides?|lecture|document|untitled|강의자료|새 문서)[\s\d_()-]*", stem):
        return stem[:80]
    first = next((line.strip() for p in pages[:2] for line in (p.get("text") or "").splitlines() if len(line.strip()) >= 3), "")
    return (first or stem or "강의자료")[:80]


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
    # 같은 파일을 다시 올리면 새로 만들지 않고 있던 자료를 연다 (같은 강의자료가 여러 개 생기지 않게)
    same = _same_document(data)
    if same is not None:
        if course.strip() and not same.get("course"):
            db().set_course(same["id"], course.strip()[:40])
        return {**db().get_document(same["id"]), "duplicate": True}
    name = title or _document_title(file.filename, pages)
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
def delete_document(doc_id: str, purge: bool = False):
    """지우기: 휴지통에 넣고 7일 뒤 완전히 지운다. purge=true 면 바로 완전히 (내 자료 모두 지우기)"""
    if db().get_document(doc_id) is None:
        raise HTTPException(404, "강의자료가 없습니다.")
    if purge:
        _purge_document(doc_id)
    else:
        db().trash_document(doc_id)


TRASH_DAYS = 7


@app.get("/trash")
def list_trash():
    for doc_id in db().expired_trash(TRASH_DAYS):
        _purge_document(doc_id)
    now = time.time()
    return [{**d, "days_left": max(0, math.ceil(TRASH_DAYS - (now - d["deleted_at"]) / 86400))} for d in db().list_trash()]


@app.post("/trash/{doc_id}/restore")
def restore_trash(doc_id: str):
    if db().get_document(doc_id, trashed=True) is None:
        raise HTTPException(404, "휴지통에 없는 자료예요.")
    db().trash_document(doc_id, restore=True)
    return {"restored": doc_id}


@app.delete("/trash/{doc_id}", status_code=204)
def purge_trash(doc_id: str):
    if db().get_document(doc_id, trashed=True) is None:
        raise HTTPException(404, "휴지통에 없는 자료예요.")
    _purge_document(doc_id)


@app.get("/account/usage")
def my_usage():
    """내 사용량: 강의자료·강의 수, 녹음 길이, 서버에서 차지하는 크기 (녹음·자료·사진)"""
    docs = db().list_documents()
    sessions = [x["id"] for d in docs for x in d["sessions"]]
    names = os.listdir(settings.upload_dir) if os.path.isdir(settings.upload_dir) else []
    size = lambda n: os.path.getsize(os.path.join(settings.upload_dir, n)) if os.path.exists(os.path.join(settings.upload_dir, n)) else 0
    audio = sum(size(n) for n in names if any(n.startswith(sid) or n == f"full-{sid}.wav" for sid in sessions))
    photos = sum(size(n) for n in names if any(n.startswith(f"photo-{sid}") for sid in sessions))
    files = sum(size(f"{d['id']}.pdf") for d in docs)
    # 녹음 길이: 받아쓴 마지막 시각 (올린 녹음 파일도 포함)
    ends = {r["session_id"]: r["end"] for r in db()._query("SELECT session_id, MAX(end_ms) AS end FROM transcript_segments GROUP BY session_id")}
    minutes = sum(ends.get(sid) or 0 for sid in sessions) // 60000
    trash = len(db().list_trash())
    return {"documents": len(docs), "lectures": len(sessions), "recorded_minutes": minutes, "trash": trash,
            "bytes": {"audio": audio, "documents": files, "photos": photos, "total": audio + files + photos}}


class AccountDelete(BaseModel):
    password: str


@app.post("/account/delete")
def delete_account(body: AccountDelete):
    """계정 삭제: 비밀번호를 한 번 더 받고, 강의자료·녹음·필기·시간표·친구·로그인을 모두 지운다 (되돌릴 수 없음)"""
    me = _me()
    user = db().user_by_name((db().get_user(me) or {}).get("name", ""))
    if not user or not auth.check_password(body.password, user["password"]):
        raise HTTPException(401, "비밀번호가 맞지 않아요.")
    for doc_id in db().owned_documents(me):
        _purge_document(doc_id)
    db().delete_user(me)
    res = JSONResponse({"deleted": True})
    res.delete_cookie(auth.COOKIE, path="/")
    return res


def _purge_document(doc_id: str) -> None:
    sessions = db().delete_document(doc_id)
    with contextlib.suppress(FileNotFoundError):
        os.remove(_pdf_path(doc_id))
    # 그 강의들의 녹음(session-n.wav, session.m4a 등)과 정리 PDF도 지운다
    if os.path.isdir(settings.upload_dir):
        for name in os.listdir(settings.upload_dir):
            if any(name.startswith(sid) or name in _session_files(sid) for sid in sessions):
                with contextlib.suppress(FileNotFoundError):
                    os.remove(os.path.join(settings.upload_dir, name))


def _session_files(sid: str) -> tuple[str, ...]:
    """강의 하나에 딸린 파일 이름들 (녹음은 sid 로 시작)"""
    return (f"notes-{sid}.pdf", f"full-{sid}.wav", f"study-{sid}.pdf")


@app.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str):
    """강의(녹음) 하나만 지운다: 받아쓰기·필기·요약·퀴즈·녹음 파일까지. 강의자료는 그대로"""
    _session_or_404(session_id)
    db().delete_session(session_id)
    if os.path.isdir(settings.upload_dir):
        for name in os.listdir(settings.upload_dir):
            if name.startswith(session_id) or name in _session_files(session_id):
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
    session_id = db().create_session(body.document_id, body.language)
    return db().get_session(session_id)


def _session_or_404(session_id: str) -> dict:
    session = db().get_session(session_id)
    if session is None or db().doc_trashed(session["document_id"]):   # 휴지통에 넣은 자료의 강의는 안 보인다
        raise HTTPException(404, "강의 세션이 없습니다.")
    return session


MAX_AUDIO_BYTES = 500 * 1024 * 1024


@app.post("/documents/from-audio")
async def document_from_audio(background: BackgroundTasks, file: UploadFile = File(...), course: str = Form(""), title: str = Form(""),
                              language: str = Form("")):
    """강의자료 없이 녹음 파일만: 노트 수업을 새로 만들고 그 녹음으로 정리한다.
    받아쓰기 → 주제가 바뀔 때마다 쪽을 나눠 주제 제목·필기 → 요약·퀴즈·플래시카드 (강의자료 수업과 같은 결과 화면)."""
    stem = os.path.splitext(file.filename or "")[0].strip()
    meaningless = not stem or re.fullmatch(r"(?i)(새로운\s*녹음|새\s*녹음|녹음|recording|new recording|audio|voice|음성\s*메모)?[\s\d_()-]*", stem)
    if len(stem) < 4:  # "rec" 같은 짧은 이름도 뜻이 없다
        meaningless = True
    name = (title.strip() or (None if meaningless else stem) or time.strftime("%m월 %d일 녹음 수업"))[:80]
    doc_id = db().create_notebook(name, "notebook")
    if course.strip():
        db().set_course(doc_id, course.strip()[:40])
    session = await session_from_audio(background, doc_id, file, language)
    return {"document_id": doc_id, "session_id": session["id"], "title": name}


@app.post("/sessions/from-audio")
async def session_from_audio(background: BackgroundTasks, document_id: str = Form(...), file: UploadFile = File(...),
                             language: str = Form("")):
    """'음성 메모' 등으로 녹음해 둔 파일로 강의를 정리한다: 받아쓰기 → 페이지 추적·필기·과제 → 요약·퀴즈."""
    if db().get_document(document_id) is None:
        raise HTTPException(404, "강의자료가 없습니다.")
    session_id = db().create_session(document_id, language)
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


def _lang(session_id: str) -> str | None:
    """강의 언어: '영어 강의'로 체크했으면 'en', 아니면 None (목소리로 정한다)"""
    return (db().get_session(session_id) or {}).get("language") or None


def _lang_kw(session_id: str) -> dict:
    lang = _lang(session_id)
    return {"language": lang} if lang else {}


async def _process_audio(session_id: str, document_id: str, path: str) -> None:
    doc = db().get_document(document_id)
    progress = app.state.progress
    progress[session_id] = 0.0
    try:
        segments = await asyncio.to_thread(
            app.state.transcriber.transcribe, path, " ".join(doc["keywords"][:40]),
            lambda p: progress.__setitem__(session_id, p), **_lang_kw(session_id),
        )
    except Exception as exc:  # 디코딩 실패, 모델 다운로드 실패 등
        log.exception("녹음 파일 받아쓰기 실패")
        db().set_session_status(session_id, "failed", _why("받아쓰기", exc))
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


def _why(step: str, exc: Exception) -> str:
    """실패 이유를 사람이 알아볼 말로 (화면에 보여 준다)"""
    text = " ".join(str(exc).split())
    if "401" in text or "invalid_api_key" in text or "Invalid API Key" in text or "GROQ_API_KEY" in text:
        hint = "Groq 키가 맞지 않아요. 서버를 다시 켜면 키를 확인하고 다시 물어봐요."
    elif "429" in text or "한도" in text:
        hint = "Groq 무료 한도에 걸렸어요. 잠시 뒤 '다시 정리하기'를 눌러 주세요."
    elif "연결할 수 없" in text or "Connect" in text:
        hint = "AI 서버에 연결할 수 없었어요. 인터넷을 확인하고 다시 해 주세요."
    elif "ffmpeg" in text.lower() or "FileNotFound" in type(exc).__name__:
        hint = "녹음 파일을 열 수 없었어요 (ffmpeg 가 없거나 파일이 깨졌을 수 있어요)."
    else:
        hint = ""
    return f"{step} 단계에서 멈췄어요. {hint} ({type(exc).__name__}: {text[:160]})".replace("  ", " ")


async def _renote(session_id: str, document_id: str, segments: list[dict]) -> None:
    """저장된 받아쓰기를 처음부터 다시 흘려 넣어 필기를 새로 만든다 (그때 본 쪽도 그대로 따라간다)"""
    async def discard(_message: dict) -> None:
        pass

    try:
        live = LiveSession(db(), app.state.llm, db().get_session(session_id), discard)
        last_page = None
        for seg in segments:
            if seg.get("page_no") and seg["page_no"] != last_page:
                last_page = seg["page_no"]
                with contextlib.suppress(Exception):
                    await live.handle({"type": "page_view", "page": last_page})
            await live.handle({"type": "transcript_final", "text": seg["text"], "start_ms": seg["start_ms"], "end_ms": seg["end_ms"],
                               "loud": bool(seg.get("loud"))})
        await live.close()
    except Exception as exc:
        log.exception("필기 다시 만들기 실패")
        db().set_session_status(session_id, "failed", _why("필기 다시 만들기", exc))
        return
    db().set_session_status(session_id, "processing")
    await _summarize(session_id, document_id)


@app.post("/sessions/{session_id}/renote")
async def renote_session(session_id: str, background: BackgroundTasks):
    """필기 다시 만들기: AI 필기만 지우고 받아쓰기로 새로 쓴다 (내가 쓰거나 고친 필기·사진·질문은 그대로)"""
    session = _session_or_404(session_id)
    if session["status"] in ("recording", "transcribing", "processing"):
        raise HTTPException(409, "지금은 강의를 정리하는 중이에요. 끝난 뒤에 다시 해 주세요.")
    doc = db().get_document(session["document_id"])
    if not db().get_segments(session_id):
        raise HTTPException(409, "다시 만들 받아쓰기가 없어요.")
    segments = db().reset_for_renote(session_id, notebook=doc["kind"] in ("notebook", "meeting"))
    db().set_session_status(session_id, "processing")
    background.add_task(_renote, session_id, session["document_id"], segments)
    return db().get_session(session_id)


@app.get("/sessions/{session_id}/snapshot")
def note_snapshot(session_id: str):
    """다시 만들기 전 필기가 남아 있으면: 그때 필기 수와 지금 필기 수 (되돌리기 버튼에 쓴다)"""
    _session_or_404(session_id)
    return db().snapshot_info(session_id)


@app.post("/sessions/{session_id}/undo-renote")
def undo_renote(session_id: str):
    """필기 다시 만들기·다시 받아쓰기를 되돌린다: 그 전의 AI 필기·받아쓰기·요약으로 (내가 쓰거나 고친 필기는 그대로)"""
    session = _session_or_404(session_id)
    if session["status"] in ("recording", "transcribing", "processing"):
        raise HTTPException(409, "지금 정리하는 중이에요. 끝난 뒤에 되돌려 주세요.")
    if not db().restore_snapshot(session_id):
        raise HTTPException(404, "되돌릴 예전 필기가 없어요.")
    db().set_session_status(session_id, "done")
    return db().get_session(session_id)


@app.post("/sessions/{session_id}/retry")
async def retry_session(session_id: str, background: BackgroundTasks):
    """정리 실패한 강의를 다시: 받아쓴 글이 없으면 저장된 녹음부터, 있으면 필기·요약만 다시"""
    session = _session_or_404(session_id)
    if session["status"] != "failed":
        raise HTTPException(409, "정리에 실패한 강의만 다시 할 수 있어요.")
    if db().get_segments(session_id):
        db().set_session_status(session_id, "processing")
        background.add_task(_summarize, session_id, session["document_id"])
    else:
        found = audio_file(session_id)
        if found is None:
            raise HTTPException(404, "이 강의는 서버에 녹음이 없어 다시 할 수 없어요.")
        db().set_session_status(session_id, "transcribing")
        background.add_task(_process_audio, session_id, session["document_id"], found[0])
    return db().get_session(session_id)


@app.post("/sessions/{session_id}/retranscribe")
async def retranscribe(session_id: str, background: BackgroundTasks):
    """녹음부터 다시 받아쓰기 (예: 한국어 강의가 영어로 받아써졌을 때). AI 필기·받아쓰기는 새로, 내가 쓴 필기는 그대로"""
    session = _session_or_404(session_id)
    if session["status"] in ("transcribing", "processing", "recording"):
        raise HTTPException(409, "지금 정리하는 중이에요. 끝난 뒤 다시 해 주세요.")
    found = audio_file(session_id)
    if found is None:
        raise HTTPException(404, "이 강의는 서버에 녹음이 없어 다시 받아쓸 수 없어요.")
    doc = db().get_document(session["document_id"])
    db().reset_for_renote(session_id, notebook=doc["kind"] in ("notebook", "meeting"))
    db().set_session_status(session_id, "transcribing")
    background.add_task(_process_audio, session_id, session["document_id"], found[0])
    return db().get_session(session_id)


@app.get("/sessions/{session_id}/glossary")
def get_glossary(session_id: str):
    """실시간 용어 사전: 강의 중에 처음 나온 전문용어와 뜻 (나온 순서대로)."""
    _session_or_404(session_id)
    return merge_concepts(db().list_terms(session_id))  # 같은 용어가 여러 번 잡히면 하나로


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


LIVE_STREAMS: dict[str, int] = {}  # 지금 녹음 소리를 보내고 있는 연결 수 (다른 기기에서 녹음 중인지 알려고)


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
    LIVE_STREAMS[session_id] = LIVE_STREAMS.get(session_id, 0) + 1
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
        LIVE_STREAMS[session_id] = LIVE_STREAMS.get(session_id, 1) - 1
        if LIVE_STREAMS[session_id] <= 0:
            LIVE_STREAMS.pop(session_id, None)
        tick_task.cancel()
        await live.close()


@app.get("/sessions/{session_id}/received")
def received_audio(session_id: str):
    """서버가 받은 실시간 녹음 길이 (ms). 폰이 가진 전체 녹음과 견줘 빠진 곳이 있는지 본다"""
    _session_or_404(session_id)
    return {"ms": recorded_ms(session_id), "live": LIVE_STREAMS.get(session_id, 0) > 0}


@app.post("/sessions/{session_id}/full-audio")
async def full_audio(session_id: str, background: BackgroundTasks, file: UploadFile = File(...)):
    """녹음 오프라인 저장: 수업 중 연결이 끊겨 서버가 못 받은 소리가 있으면, 폰이 모아 둔 전체 녹음을 올린다.
    그 파일을 이 강의의 녹음으로 삼아 처음부터 다시 받아쓰고 정리한다 (내가 쓴 필기는 그대로)."""
    session = _session_or_404(session_id)
    os.makedirs(settings.upload_dir, exist_ok=True)
    path = os.path.join(settings.upload_dir, f"{session_id}.audio")
    size = 0
    with open(path + ".part", "wb") as f:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_AUDIO_BYTES:
                f.close()
                os.remove(path + ".part")
                raise HTTPException(413, "녹음 파일이 너무 커요.")
            f.write(chunk)
    if size < 1000:
        os.remove(path + ".part")
        raise HTTPException(400, "녹음이 비어 있어요.")
    os.replace(path + ".part", path)
    doc = db().get_document(session["document_id"])
    db().reset_for_renote(session_id, notebook=doc["kind"] in ("notebook", "meeting"))
    db().set_session_status(session_id, "transcribing")
    background.add_task(_process_audio, session_id, session["document_id"], path)
    return db().get_session(session_id)


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
            lambda p: progress.__setitem__(session_id, p), **_lang_kw(session_id))
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
    except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError) as exc:
        log.exception("요약·퀴즈 생성 실패")
        db().set_session_status(session_id, "failed", _why("필기·요약", exc))
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
def get_summary(session_id: str, background: BackgroundTasks):
    session = _session_or_404(session_id)
    summary = db().get_summary(session_id)
    # 예전 방식으로 만든 퀴즈("몇 쪽에서 다룬 내용은?", 슬라이드 베끼기)는 새 방식으로 다시 낸다 (한 번만, 뒤에서)
    if summary and session["status"] == "done" and _old_quiz(session_id, summary) and session_id not in app.state.quiz_jobs:
        app.state.quiz_jobs.add(session_id)
        background.add_task(_remake_quiz, session_id)
    return {"status": session["status"], "error": session.get("error"), "summary": summary, "quiz_status": "making" if session_id in app.state.quiz_jobs else "ready",
            "progress": app.state.progress.get(session_id), "review": app.state.reviews.get(session_id),
            "engine": getattr(app.state.transcriber, "engine", None)}


def _quiz_inputs(session_id: str) -> tuple[list[dict], list[dict], list[dict]]:
    session = db().get_session(session_id)
    pages = db().list_pages(session["document_id"])
    return pages, db().get_segments(session_id), db().list_annotations(session_id)


def _old_quiz(session_id: str, summary: dict) -> bool:
    quiz = summary.get("quiz") or []
    if not quiz:
        return False
    pages, segments, _ = _quiz_inputs(session_id)
    sources = [p.get("text") or "" for p in pages] + [s["text"] for s in segments]
    return len(clean_quiz(quiz, sources, {p["page_no"] for p in pages})) < len(quiz)


async def _remake_quiz(session_id: str) -> None:
    try:
        make = getattr(app.state.llm, "make_quiz", None)
        if make is None:
            return
        pages, segments, notes = _quiz_inputs(session_id)
        summary = db().get_summary(session_id) or {}
        results = [(p["page_no"], p["summary"], None, 1) for p in summary.get("pages", [])]
        quiz = await make(pages, segments, notes, results)
        if quiz:
            db().save_summary(session_id, {**summary, "quiz": quiz})
    except Exception:
        log.exception("퀴즈 다시 내기 실패")
    finally:
        app.state.quiz_jobs.discard(session_id)


@app.post("/sessions/{session_id}/quiz")
async def remake_quiz(session_id: str, background: BackgroundTasks):
    """퀴즈 새로 받기: 같은 강의로 다른 문제를 AI가 다시 낸다"""
    _session_or_404(session_id)
    if session_id not in app.state.quiz_jobs:
        app.state.quiz_jobs.add(session_id)
        background.add_task(_remake_quiz, session_id)
    return {"quiz_status": "making"}


# AI 퀴즈: AI가 강의자료·수업 내용을 먼저 공부하고, 시험처럼 여러 유형(객관식·OX·빈칸·단답·서술)의 문제를 하나씩 낸다.
# 학생이 답하면 AI가 채점한다 (객관식·OX·글자가 같은 답은 바로, 나머지는 AI가 채점 기준으로)


class QuizSetRequest(BaseModel):
    count: int = 8


def _session_material(session_id: str) -> dict:
    summary = db().get_summary(session_id) or {}
    by_page: dict[int, list[str]] = {}
    for p in summary.get("pages", []):
        by_page.setdefault(p["page_no"], []).append(p["summary"])
    return {"segments": db().get_segments(session_id), "annotations": db().list_annotations(session_id), "summaries": by_page}


def _public_set(set_id: int, body: dict) -> dict:
    """학생에게 보낼 때: 아직 안 푼 문제는 정답을 빼고"""
    questions = []
    for i, q in enumerate(body["questions"]):
        done = i < len(body["answers"])
        item = {"index": i, "type": q["type"], "type_label": quizlib.TYPE_LABEL[q["type"]], "page_no": q["page_no"],
                "topic": q.get("topic", ""), "question": q["question"], "choices": q.get("choices", [])}
        if done:
            item |= {"answer": q["answer"], "explanation": q.get("explanation", ""), "result": body["answers"][i]}
        questions.append(item)
    graded = body["answers"]
    return {"id": set_id, "title": body.get("title", ""), "questions": questions,
            "score": round(sum(a["score"] for a in graded), 1), "answered": len(graded)}


async def _make_quiz_set(document_id: str, session_ids: list[str], count: int, title: str) -> dict:
    make = getattr(app.state.llm, "quiz_set", None)
    if make is None:
        raise HTTPException(503, "지금 AI가 퀴즈를 낼 수 없어요.")
    pages = db().list_pages(document_id)
    material = quizlib.material(pages, [_session_material(s) for s in session_ids])
    if len(material) < 40:
        raise HTTPException(409, "퀴즈를 낼 만큼 강의 내용이 아직 없어요.")
    count = max(3, min(count, 15))
    page_nos = {p["page_no"] for p in pages}
    questions: list[dict] = []
    try:
        for _ in range(2):  # 쓸 만한 문제가 모자라면 한 번 더
            questions += quizlib.clean_set(await make(quizlib.quiz_prompt(material, count, quizlib.TYPES)), page_nos)
            if len(questions) >= min(count, 4):
                break
    except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError):
        log.exception("AI 퀴즈 만들기 실패")
    if not questions:
        raise HTTPException(502, "AI가 문제를 내지 못했어요. 잠시 뒤 다시 해 주세요.")
    # 같은 질문 빼고, 유형이 한쪽으로 몰리지 않게 섞는다
    seen, unique = set(), []
    for q in questions:
        key = quizlib._norm(q["question"])
        if key not in seen:
            seen.add(key)
            unique.append(q)
    order = sorted(range(len(unique)), key=lambda i: (sum(1 for q in unique[:i] if q["type"] == unique[i]["type"]), i))
    body = {"title": title, "questions": [unique[i] for i in order][:count], "answers": []}
    set_id = db().add_quiz_set(document_id, session_ids[0] if len(session_ids) == 1 else None, body)
    return _public_set(set_id, body)


@app.post("/sessions/{session_id}/quiz-set")
async def session_quiz_set(session_id: str, body: QuizSetRequest = QuizSetRequest()):
    session = _session_or_404(session_id)
    return await _make_quiz_set(session["document_id"], [session_id], body.count, "이번 강의")


@app.post("/documents/{document_id}/quiz-set")
async def document_quiz_set(document_id: str, body: QuizSetRequest = QuizSetRequest()):
    doc = db().get_document(document_id)
    if doc is None:
        raise HTTPException(404, "강의자료가 없습니다.")
    sessions = [s["id"] for d in db().list_documents() if d["id"] == document_id for s in d["sessions"]]
    return await _make_quiz_set(document_id, sessions, body.count, doc.get("title") or "강의자료 전체")


@app.get("/quiz-sets/{set_id}")
def get_quiz_set(set_id: int):
    row = db().get_quiz_set(set_id)
    if row is None:
        raise HTTPException(404, "퀴즈가 없습니다.")
    return _public_set(set_id, row["body"])


class GradeRequest(BaseModel):
    index: int
    answer: str


@app.get("/documents/{doc_id}/weak")
def weak_notes(doc_id: str):
    """약점 노트: 퀴즈에서 틀린 문제 + 수업 중 '모르겠어요' + 복습에서 자주 틀린 카드 (많이 틀린 것부터)"""
    if db().get_document(doc_id) is None:
        raise HTTPException(404, "강의자료가 없습니다.")
    _sync_cards(doc_id)
    cards = [c for c in db().list_cards(doc_id) if c["source"] in ("quiz", "confused") or c["lapses"] > 0]
    cards.sort(key=lambda c: (-c["lapses"], c["source"] != "quiz", c["page_no"] or 0))
    return [{k: c[k] for k in ("card_key", "source", "front", "back", "page_no", "lapses", "reps")} for c in cards]


@app.post("/quiz-sets/{set_id}/grade")
async def grade_quiz_answer(set_id: int, body: GradeRequest):
    row = db().get_quiz_set(set_id)
    if row is None:
        raise HTTPException(404, "퀴즈가 없습니다.")
    data = row["body"]
    if body.index != len(data["answers"]) or body.index >= len(data["questions"]):
        raise HTTPException(409, "이 문제는 지금 채점할 수 없어요.")
    q = data["questions"][body.index]
    result = quizlib.quick_grade(q, body.answer)
    if result is None:
        try:
            graded = await app.state.llm.grade_answer(quizlib.grade_prompt(q, body.answer))
            verdict = graded.get("verdict") if graded.get("verdict") in ("correct", "partial", "wrong") else "wrong"
            score = {"correct": 1.0, "wrong": 0.0}.get(verdict, min(max(float(graded.get("score", 0.5)), 0.1), 0.9))
            result = {"verdict": verdict, "score": score, "feedback": graded.get("feedback", "")}
        except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
            log.exception("AI 채점 실패")
            raise HTTPException(502, "AI가 채점하지 못했어요. 다시 보내 주세요.")
    data["answers"].append({**result, "given": body.answer})
    db().save_quiz_set(set_id, data)
    # 오답 노트: 틀리거나 반만 맞은 문제는 복습 카드로 (잊기 곡선대로 다시 나온다)
    if result["verdict"] != "correct" and q.get("question"):
        key = card_key("quiz", q["question"])
        back = f"정답: {q.get('answer', '')}" + (f"\n\n{q['explanation']}" if q.get("explanation") else "") + f"\n\n내가 쓴 답: {body.answer}"
        db().upsert_card(key, row["document_id"], "quiz", q["question"], back, q.get("page_no"))
        db().due_now_if_new(key)
    return _public_set(set_id, data)["questions"][body.index] | {"done": len(data["answers"]) == len(data["questions"])}


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
        if kind == "concepts":
            body = merge_concepts(body)
        db().save_study(session_id, kind, digest, body)
    finally:
        app.state.study_jobs.pop((session_id, kind), None)


def _study_status(session_id: str, kind: str, digest: str) -> dict:
    job = app.state.study_jobs.get((session_id, kind))
    if job:
        return {**job, "body": None}
    saved = db().get_study(session_id, kind)
    if saved:
        body = merge_concepts(saved[1]) if kind == "concepts" and isinstance(saved[1], list) else saved[1]  # 예전에 만든 것도
        return {"status": "ready", "done": 0, "total": 0, "body": body, "stale": saved[0] != digest}
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
    scope: str = "lecture"     # AI 튜터 범위: lecture(이 강의) · course(이 과목의 모든 강의) · all(학기 전체)
    course: str | None = None  # 학기 튜터에서 과목만


@app.post("/sessions/{session_id}/tutor")
async def tutor(session_id: str, body: TutorRequest):
    """AI 튜터: 질문과 가까운 쪽들의 슬라이드·설명·필기를 근거로 답한다. 대화 기록은 앱이 들고 있다가 보낸다.
    scope 로 범위를 넓힐 수 있다: course = 이 강의자료 과목의 모든 강의, all = 학기 전체"""
    if body.scope in ("course", "all"):
        session = _session_or_404(session_id)
        doc = db().get_document(session["document_id"])
        course = (doc.get("course") or "") if body.scope == "course" else None
        return await _semester_answer(body, course=course, only_doc=doc["id"] if body.scope == "course" and not course else None)
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


# AI 정리 노트 PDF: AI 가 배운 내용을 주제별로 다시 정리한 노트 (study_note.py)


def _study_pdf_path(session_id: str) -> str:
    return os.path.join(settings.upload_dir, f"study-{session_id}.pdf")


def _study_pdf_status(session_id: str) -> dict:
    state = app.state.study_pdf.get(session_id)
    if state:
        return state
    return {"status": "ready" if os.path.exists(_study_pdf_path(session_id)) else "none"}


async def _build_study_pdf(session_id: str) -> None:
    from .study_note import build_study_pdf, clean_note, study_prompt

    state = app.state.study_pdf[session_id]
    try:
        session = db().get_session(session_id)
        doc = db().get_document(session["document_id"])
        material = quizlib.material(db().list_pages(doc["id"]), [_session_material(session_id)], limit=20000)
        if len(material) < 40:
            state.update(status="failed", error="정리할 강의 내용이 아직 없어요.")
            return
        note = clean_note(await app.state.llm.study_note(study_prompt(material, doc["title"], db().list_terms(session_id))), doc["title"])
        if not note["sections"]:
            state.update(status="failed", error="AI 가 정리 노트를 쓰지 못했어요. 다시 해 주세요.")
            return
        data = await asyncio.to_thread(build_study_pdf, note, doc["title"], session["started_at"])
        os.makedirs(settings.upload_dir, exist_ok=True)
        with open(_study_pdf_path(session_id), "wb") as f:
            f.write(data)
    except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError) as exc:
        log.exception("정리 노트 만들기 실패")
        state.update(status="failed", error=_why("정리 노트", exc))
        return
    app.state.study_pdf.pop(session_id, None)


@app.post("/sessions/{session_id}/study-pdf", status_code=202)
def start_study_pdf(session_id: str, background: BackgroundTasks):
    """AI 정리 노트 PDF 를 (다시) 만든다"""
    _session_or_404(session_id)
    if _study_pdf_status(session_id)["status"] != "building":
        app.state.study_pdf[session_id] = {"status": "building"}
        background.add_task(_build_study_pdf, session_id)
    return _study_pdf_status(session_id)


@app.get("/sessions/{session_id}/study-pdf/status")
def study_pdf_status(session_id: str):
    _session_or_404(session_id)
    return _study_pdf_status(session_id)


@app.get("/sessions/{session_id}/study-pdf")
def get_study_pdf(session_id: str, download: bool = False):
    session = _session_or_404(session_id)
    if not os.path.exists(_study_pdf_path(session_id)):
        raise HTTPException(404, "정리 노트가 아직 없습니다.")
    title = db().get_document(session["document_id"])["title"]
    return FileResponse(_study_pdf_path(session_id), media_type="application/pdf", filename=f"{title} 정리 노트.pdf",
                        content_disposition_type="attachment" if download else "inline")


@app.get("/sessions/{session_id}/notes-pdf/status")
def notes_pdf_status(session_id: str):
    _session_or_404(session_id)
    return _notes_pdf_status(session_id)


@app.get("/sessions/{session_id}/notes-pdf")
def get_notes_pdf(session_id: str, download: bool = False):
    session = _session_or_404(session_id)
    if not os.path.exists(_notes_pdf_path(session_id)):
        raise HTTPException(404, "정리 PDF가 아직 없습니다.")
    title = db().get_document(session["document_id"])["title"]
    return FileResponse(_notes_pdf_path(session_id), media_type="application/pdf", filename=f"{title} 정리.pdf",
                        content_disposition_type="attachment" if download else "inline")


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
    task = _task_or_404(task_id)
    if body.due_on is not None:
        if body.due_on and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", body.due_on):
            raise HTTPException(422, "마감일은 YYYY-MM-DD 로 적어 주세요.")
        task = db().set_task_due(task_id, body.due_on)
    if body.done is not None:
        task = db().set_task_done(task_id, body.done)
    if body.checked or (body.title and body.title.strip()):
        task = db().check_task(task_id, (body.title or "").strip()[:200] or None)
    return task


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int):
    """AI 가 잘못 찾은 과제 지우기"""
    _task_or_404(task_id)
    db().delete_task(task_id)


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
    if body.type is not None:
        if body.type not in ("explanation", "example", "emphasis", "exam", "notice", "tip", "qa"):
            raise HTTPException(400, "필기 종류가 이상해요.")
        annotation = db().set_annotation_type(ann_id, body.type)
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
    db().set_mark_explanation(mark_id, answer)
    await _mark_question(db().get_mark(mark_id))
    return db().get_mark(mark_id)


async def _mark_question(mark: dict) -> None:
    """복습 카드 앞면: 교수님 말을 그대로 쓰지 않고, AI가 설명을 읽고 핵심을 묻는 질문을 만든다"""
    make = getattr(app.state.llm, "card_question", None)
    if make is None or not mark.get("explanation"):
        return
    session = db().get_session(mark["session_id"])
    page = next((p for p in db().list_pages(session["document_id"]) if p["page_no"] == mark["page_no"]), {}) if session else {}
    try:
        question = await make(quizlib.card_prompt(mark["explanation"], mark["speech"], page.get("text") or ""))
    except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError):
        log.exception("복습 카드 질문 만들기 실패")
        return
    if 4 <= len(question) <= 120:
        db().set_mark_question(mark["id"], question)


async def _fill_mark_questions(marks: list[dict]) -> None:
    for mark in marks[:10]:
        await _mark_question(mark)


@app.delete("/marks/{mark_id}", status_code=204)
def delete_mark(mark_id: int):
    if not db().delete_mark(mark_id):
        raise HTTPException(404, "표시가 없습니다.")


# 족보 노트: 한 강의자료의 모든 강의에서 시험에 필요한 것만 모은 한 장 (AI 없이 이미 만든 것을 모은다)


@app.get("/documents/{doc_id}/jokbo")
def jokbo(doc_id: str):
    return _jokbo(doc_id, with_friends=True)


def _jokbo(doc_id: str, with_friends: bool):
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
    shared = db().list_shared(doc_id) + (_friend_sheets(doc_id) if with_friends else [])
    return build_jokbo({**doc, "pages": pages}, sessions, scores, top, questions, shared)


# 망각 곡선 복습: 플래시카드·예상 문제·"모르겠다" 설명을 카드로 모아, 틀린 것은 자주 아는 것은 드물게


def _sync_cards(doc_id: str) -> list[dict]:
    """카드를 모으고, AI 질문이 아직 없는 "모르겠다" 표시를 돌려준다 (뒤에서 질문을 만든다)"""
    missing = []
    titles = {p["page_no"]: quizlib.page_title(p.get("text") or "") for p in db().list_pages(doc_id)}
    for sid in db().session_ids(doc_id):
        saved = db().get_study(sid, "flashcards")
        for card in (saved[1] if saved else []) or []:
            front, back = str(card.get("front", "")).strip(), str(card.get("back", "")).strip()
            if front and back:
                db().upsert_card(card_key("flashcard", front), doc_id, "flashcard", front, back, card.get("page_no"))
        for mark in db().list_marks(sid):
            if mark["explanation"]:
                # 앞면은 질문 (교수님 말 그대로는 무엇을 묻는지 알 수 없어서), 그때 들은 말은 뒷면 아래에 참고로
                topic = titles.get(mark["page_no"]) or f"{mark['page_no']}쪽"
                front = mark.get("question") or f"'{topic}'에서 헷갈렸던 개념, 이제 설명할 수 있나요?"
                if not mark.get("question"):
                    missing.append(mark)
                heard = " ".join(mark["speech"].split())[-90:]
                back = mark["explanation"] + (f"\n\n수업 중 헷갈렸던 말: “…{heard}”" if heard else "")
                db().upsert_card(card_key("confused", str(mark["id"])), doc_id, "confused", front, back, mark["page_no"])
    for p in db().get_document(doc_id)["pages"]:
        cached = db().get_exam_questions(doc_id, p["page_no"])
        for q in (cached[1] if cached else []):
            if q.get("question") and q.get("answer"):
                db().upsert_card(card_key("exam", q["question"]), doc_id, "exam", q["question"], q["answer"], p["page_no"])
    return missing


SOURCE_ORDER = {"quiz": 0, "confused": 1, "exam": 2, "flashcard": 3}


def _after(seconds: float) -> str:
    days = seconds / 86400
    if days < 0.5:
        return "오늘 다시"
    return f"{round(days)}일 뒤" if days < 30 else f"{round(days / 30)}달 뒤"


@app.get("/review/today")
def review_today(background: BackgroundTasks, document_id: str | None = None):
    docs = [document_id] if document_id else [d["id"] for d in db().list_documents()]
    titles = {d["id"]: d["title"] for d in db().list_documents()}
    missing = []
    for doc_id in docs:
        if doc_id in titles:
            missing += _sync_cards(doc_id)
    if missing and not getattr(app.state, "mark_questions_running", False):
        app.state.mark_questions_running = True

        async def fill():
            try:
                await _fill_mark_questions(missing)
            finally:
                app.state.mark_questions_running = False
        background.add_task(fill)
    cards = [c for doc_id in docs for c in db().list_cards(doc_id)]
    now = time.time()
    due = sorted((c for c in cards if c["due_at"] is not None and c["due_at"] <= now), key=lambda c: (-c["lapses"], c["due_at"]))
    # 오늘 처음 본 카드 수만큼 새 카드를 덜 꺼낸다
    started_today = sum(1 for c in cards if c["last_at"] and c["reps"] <= 1 and c["lapses"] == 0 and now - c["last_at"] < 86400)
    fresh = sorted((c for c in cards if c["due_at"] is None), key=lambda c: (SOURCE_ORDER.get(c["source"], 9), c["created_at"]))
    fresh = fresh[:max(0, NEW_PER_DAY - started_today)]
    upcoming = min((c["due_at"] for c in cards if c["due_at"] and c["due_at"] > now), default=None)
    def preview(c: dict) -> dict:
        # 버튼마다 다음 복습이 언제인지 ("1일 뒤")
        return {g: _after(schedule(c, n, now)["due_at"] - now) for g, n in GRADES.items()}
    return {"cards": [{**c, "title": titles.get(c["document_id"], ""), "new": c["due_at"] is None, "next": preview(c)} for c in due + fresh],
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
            out.append({"doc_id": doc["id"], "doc_title": doc["title"], "session_id": s["id"], "started_at": s["started_at"],
                        "course": doc.get("course") or ""})
    return out


@app.get("/semester/concepts")
def semester_concepts():
    lectures = [{**lec, "terms": db().list_terms(lec["session_id"])} for lec in _lectures()]
    return concept_map(lectures)


@app.post("/semester/tutor")
async def semester_tutor(body: TutorRequest):
    """여러 강의를 넘나드는 질문 ("3주차랑 7주차 차이가 뭐야?"): 모든 강의의 쪽 중에서 가까운 것만 근거로. course 를 주면 그 과목만"""
    return await _semester_answer(body, course=(body.course or "").strip() or None)


async def _semester_answer(body: TutorRequest, course: str | None = None, only_doc: str | None = None):
    messages = [m.model_dump() for m in body.messages if m.content.strip()][-10:]
    if not messages or messages[-1]["role"] != "user":
        raise HTTPException(400, "질문이 없어요.")
    chunks = []
    for lec in _lectures():
        if (course and lec.get("course") != course) or (only_doc and lec["doc_id"] != only_doc):
            continue
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


@app.get("/documents/{doc_id}/exam-story")
def exam_story(doc_id: str):
    doc = db().get_document(doc_id)
    if doc is None:
        raise HTTPException(404, "강의자료가 없습니다.")
    sessions = []
    for sid in db().session_ids(doc_id):
        session = db().get_session(sid)
        sessions.append({"id": sid, "started_at": session["started_at"], "annotations": db().list_annotations(sid),
                         "segments": db().get_segments(sid), "marks": db().list_marks(sid)})
    return build_exam_story(doc["title"], sessions)


@app.get("/tasks")
def all_tasks():
    """모든 강의에서 받은 과제를 한데 모아 (홈의 할 일). 안 끝낸 것이 먼저, 그다음 최근 강의 순"""
    out = []
    for d in db().list_documents():
        for s in d["sessions"]:
            for t in db().list_tasks(s["id"]):
                guess = parse_due(t["due_text"], s["started_at"])
                out.append({**t, "doc_id": d["id"], "doc_title": d["title"], "course": d.get("course") or "", "started_at": s["started_at"],
                            "due_date": t["due_on"] or (guess.isoformat() if guess else None)})
    return sorted(out, key=lambda t: (t["done"], -t["started_at"]))


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


class NextDoc(BaseModel):
    course: str
    doc_id: str | None = None


def _next_key() -> str:
    return f"next_docs:{auth.CURRENT_USER.get() or ''}"


@app.get("/timetable/next")
def next_docs():
    """과목마다 다음 수업에 쓸 강의자료 (미리 연결). 고른 게 없으면 그 과목에서 아직 녹음 안 한 가장 새 자료를 쓴다."""
    picked: dict = json.loads(db().get_setting(_next_key()) or "{}")
    docs = db().list_documents()
    by_id = {d["id"]: d for d in docs}
    out = {}
    for course in {c["course"] for c in db().list_classes()}:
        doc = by_id.get(picked.get(course, ""))
        auto = False
        if doc is None:
            fresh = [d for d in docs if (d.get("course") or "") == course and not d.get("sessions")]
            doc = max(fresh, key=lambda d: d.get("created_at") or 0, default=None)
            auto = doc is not None
        if doc:
            out[course] = {"doc_id": doc["id"], "title": doc["title"], "auto": auto}
    return out


@app.put("/timetable/next")
def set_next_doc(body: NextDoc):
    picked: dict = json.loads(db().get_setting(_next_key()) or "{}")
    if body.doc_id:
        if db().get_document(body.doc_id) is None:
            raise HTTPException(404, "강의자료가 없습니다.")
        picked[body.course] = body.doc_id
    else:
        picked.pop(body.course, None)
    db().set_setting(_next_key(), json.dumps(picked, ensure_ascii=False))
    return next_docs()


def add_timetable_check(body: ClassCreate) -> None:
    clock = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
    if not body.course.strip():
        raise HTTPException(400, "과목 이름을 적어 주세요.")
    if not clock.match(body.start) or not clock.match(body.end) or body.start >= body.end:
        raise HTTPException(400, f"{body.course} 시간은 09:00 처럼 적고, 끝나는 시간이 시작보다 늦어야 해요.")


@app.post("/timetable")
def add_timetable(body: ClassCreate):
    add_timetable_check(body)
    return db().add_class(body.course.strip()[:40], body.weekday, body.start, body.end, body.place.strip()[:40])


def _shrink_image(data: bytes, mime: str, longest: int = 2400) -> tuple[bytes, str]:
    """사진 읽는 AI 에 보내기 전에 긴 변을 1600px 로 (휴대폰 캡처는 크고, Groq 는 4MB 까지만 받는다)"""
    try:
        pix = pymupdf.Pixmap(data)
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
        if pix.n != 3:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        while max(pix.width, pix.height) > longest:   # 반씩 줄이기 (흐려지지 않게)
            pix.shrink(1)
        return pix.tobytes("jpg", jpg_quality=88), "image/jpeg"
    except Exception:  # 못 줄이면 그대로
        return data, mime


@app.post("/timetable/from-image")
async def timetable_from_image(file: UploadFile = File(...)):
    """시간표 캡처(에브리타임·학교 포털·종이 사진)를 읽어 수업 목록을 돌려준다. 저장은 사람이 확인한 뒤 /timetable/bulk 로"""
    data = await file.read()
    if not data:
        raise HTTPException(400, "사진이 비어 있어요.")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "사진은 12MB 이하만 올릴 수 있어요.")
    mime = file.content_type if (file.content_type or "").startswith("image/") else "image/png"
    image, mime = _shrink_image(data, mime)
    # 시각은 그림에서 직접 잰다 (정확), 과목 이름은 AI 가 읽는다
    found = await asyncio.to_thread(find_blocks, data)   # 원본 크기로 재야 정확하다
    if found is None:
        found = await asyncio.to_thread(find_blocks, image)
    ai_rows, ai_error = [], ""
    try:
        ai_rows = clean_timetable(await app.state.llm.read_timetable(image, mime))
    except Exception as exc:  # AI 가 안 돼도 잰 칸은 돌려준다 (이름만 사람이 적는다)
        log.exception("시간표 사진 읽기 실패")
        ai_error = str(exc)
    rows = combine_timetable(found, ai_rows)
    # AI 가 이름을 못 읽은 칸은 서버의 한국어 글자 인식으로 칸 안의 글을 직접 읽는다
    # (이름은 읽었는데 강의실이 빈 칸도 칸 안의 글에서 강의실을 채운다)
    if any(not r["course"] or not r["place"] for r in rows if "_box" in r):
        try:
            rgb = await asyncio.to_thread(load_rgb, data)
            for r in rows:
                if (not r["course"] or not r["place"]) and "_box" in r:
                    name, place = name_and_place(await asyncio.to_thread(read_block, rgb, r["_box"], r["_color"]))
                    r["course"] = r["course"] or name
                    r["place"] = r["place"] or place
        except Exception:
            log.exception("시간표 글자 인식 실패")
    for r in rows:
        r.pop("_box", None); r.pop("_color", None)
    if not rows:
        if ai_error:
            raise HTTPException(502, f"시간표 사진을 읽지 못했어요. 직접 넣어 주세요. (이유: {ai_error[:160]})")
        raise HTTPException(422, "사진에서 수업을 찾지 못했어요. 시간표 전체가 보이게 캡처해 주세요.")
    unnamed = sum(1 for r in rows if not r["course"])
    note = ""
    if unnamed:
        note = (f"과목 이름을 {unnamed}개 못 읽었어요. 빈 칸에 이름을 적어 주세요."
                + (" (사진 속 글을 다 읽지 못했어요)" if ai_error else ""))
    return {"classes": rows, "note": note, "ai_error": ai_error[:300]}


class ClassBulk(BaseModel):
    classes: list[ClassCreate]
    replace: bool = False  # true = 지금 시간표를 지우고 이것으로 바꾸기


@app.post("/timetable/bulk")
def add_timetable_bulk(body: ClassBulk):
    """사진에서 읽고 사람이 확인한 수업을 한 번에 넣는다"""
    for c in body.classes:
        add_timetable_check(c)
    if body.replace:
        for old in db().list_classes():
            db().delete_class(old["id"])
    have = {(c["course"], c["weekday"], c["start"]) for c in db().list_classes()}
    for c in body.classes:
        if (c.course.strip(), c.weekday, c.start) not in have:
            db().add_class(c.course.strip()[:40], c.weekday, c.start, c.end, c.place.strip()[:40])
    return db().list_classes()


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
    segments = db().get_segments(session_id)
    note_text = await _read_photo_note(data, mime, " ".join(x["text"] for x in segments[-20:]))
    at = max((s["end_ms"] for s in segments), default=0)
    note = db().add_annotation(session_id, page["id"], None, "example", note_text[:1500], at)
    db().link_photo(photo_id, note["id"])
    return {**note, "photo_id": photo_id}


async def _read_photo_note(data: bytes, mime: str, speech: str) -> str:
    """사진 → 필기 글. 사진 읽는 AI 가 있으면 그것으로, 없으면(지금 Groq 무료에는 없음) 서버의 한국어 글자 인식으로 읽고
    글 모델이 띄어쓰기·오타를 다듬는다. 다 안 되면 읽은 줄 그대로, 그것도 없으면 사진만 남긴다"""
    try:
        read = await app.state.llm.read_board(data, mime)
        summary, text = str(read.get("summary", "")).strip(), str(read.get("text", "")).strip()
        if summary or text:
            return f"칠판: {summary}" + (f"\n{text}" if text else "")
    except Exception as exc:
        log.info("사진 읽는 AI 없음 → 글자 인식으로: %s", str(exc)[:120])
    lines = await asyncio.to_thread(ocr.read_photo, data)
    if not lines:
        return "칠판 사진 (글을 읽지 못했어요)"
    try:
        tidy = getattr(app.state.llm, "tidy_board", None)
        if tidy:
            read = await tidy(lines, speech)
            summary, text = str(read.get("summary", "")).strip(), str(read.get("text", "")).strip()
            if text:
                return f"칠판: {summary}" + f"\n{text}"
    except Exception:
        log.exception("판서 다듬기 실패 (읽은 글 그대로 남김)")
    return "칠판 (사진에서 읽은 글)\n" + "\n".join(lines)


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


def _share_body(sheet: dict) -> dict:
    body = {k: sheet[k] for k in ("exam", "emphasis", "notice", "terms", "predicted")}
    body["confused"] = [c for c in sheet["confused"] if c["explanation"]]
    return body


def _shares_with(owner: str, viewer: str) -> dict | None:
    """owner 가 viewer 에게 보여 주는 설정 (친구가 아니거나 이 친구를 숨겼으면 None)"""
    if viewer not in db().friend_ids(owner) or not db().pair(owner, viewer)["share"]:
        return None
    return (db().get_user(owner) or {}).get("prefs")



def _course_key(name: str) -> str:
    return re.sub(r"[\s()\[\]·\-_]", "", name or "").lower()


def _visible_courses(owner: str, prefs: dict) -> set[str]:
    """친구가 나에게 보여 주는 과목만 (족보로 공개한 과목 + 공개한 시간표의 과목). 비공개면 아무것도 모른다."""
    seen = set(prefs.get("share_courses") or []) if prefs.get("share_jokbo") else set()
    if prefs.get("share_timetable"):
        token = auth.CURRENT_USER.set(owner)
        try:
            seen |= {c["course"] for c in db().list_classes()}
        finally:
            auth.CURRENT_USER.reset(token)
    return {_course_key(c) for c in seen if c}

def _friend_sheets(doc_id: str) -> list[dict]:
    """친구 족보 자동으로: 친구가 같은 강의자료(같은 PDF)로 들은 강의가 있으면 파일을 주고받지 않아도 합친다.
    족보에 들어가는 것 중 친구가 공개한 항목만 쓰고, 녹음·받아쓰기는 보지 않는다.
    내 설정(친구 족보 합치기 · 이 친구 합치기 · 이 자료에 합치기)과 친구 설정(족보 공개 · 나에게 공개 · 그 자료 공개)을 모두 따른다."""
    me = auth.CURRENT_USER.get()
    if not me:
        return []
    my = (db().get_user(me) or {}).get("prefs", {})
    if not my.get("merge_jokbo", True) or not db().doc_friend_flags(doc_id)["merge"]:
        return []
    mine = _fingerprint(doc_id)
    out = []
    for fid in db().friend_ids(me):
        if not db().pair(me, fid)["merge"]:
            continue
        theirs = _shares_with(fid, me)
        if not theirs or not theirs.get("share_jokbo", True):
            continue
        token = auth.CURRENT_USER.set(fid)
        try:
            for d in db().list_documents():
                if (_fingerprint(d["id"]) == mine and db().session_ids(d["id"])
                        and db().doc_friend_flags(d["id"])["share"]
                        and (d.get("course") or "") in (theirs.get("share_courses") or [])):
                    friend = db().get_user(fid)
                    body = _share_body(_jokbo(d["id"], with_friends=False))
                    items = set(theirs.get("items") or [])
                    out.append({"id": f"friend-{fid}", "nickname": friend["name"] if friend else "친구", "friend": True,
                                "created_at": time.time(), "body": {k: (v if k in items else []) for k, v in body.items()}})
                    break
        finally:
            auth.CURRENT_USER.reset(token)
    return out


# 친구: 친구 코드로 신청 → 받은 사람이 수락. 친구끼리는 같은 강의자료의 족보가 저절로 합쳐진다


class FriendRequest(BaseModel):
    code: str


def _me() -> str:
    me = auth.CURRENT_USER.get()
    if not auth.enabled() or not me:
        raise HTTPException(400, "친구 기능은 로그인해서 쓸 때만 있어요.")
    return me


class FriendPrefsUpdate(BaseModel):
    share_courses: list[str] | None = None   # 족보를 공유할 과목 (빈 목록 = 공유 안 함)
    share_jokbo: bool | None = None
    share_timetable: bool | None = None
    merge_jokbo: bool | None = None
    allow_requests: bool | None = None
    items: list[str] | None = None


@app.patch("/friends/settings")
def update_friend_settings(body: FriendPrefsUpdate):
    """친구 설정: 내 족보 공개 · 내 시간표 공개 · 친구 족보 합치기 · 공개할 족보 항목 · 친구 신청 받기"""
    from .db import JOKBO_ITEMS

    change = {k: v for k, v in body.model_dump().items() if v is not None}
    if "share_courses" in change:
        change["share_courses"] = [c.strip()[:40] for c in change["share_courses"] if c.strip()][:50]
        change["share_jokbo"] = bool(change["share_courses"])
    if "items" in change:
        change["items"] = [i for i in JOKBO_ITEMS if i in change["items"]]
    db().set_friend_prefs(_me(), change)
    return list_friends()


class PairUpdate(BaseModel):
    share: bool | None = None
    merge: bool | None = None


@app.patch("/friends/{other}/settings")
def update_pair(other: str, body: PairUpdate):
    """친구 한 명에 대한 설정: 이 친구에게 내 것 보여 주기 · 이 친구 족보 합치기"""
    me = _me()
    _friend_or_403(me, other)
    db().set_pair(me, other, {k: v for k, v in body.model_dump().items() if v is not None})
    return list_friends()


class DocFriendUpdate(BaseModel):
    share: bool | None = None
    merge: bool | None = None


@app.patch("/documents/{doc_id}/friends")
def update_doc_friends(doc_id: str, body: DocFriendUpdate):
    """이 강의자료의 족보를 친구에게 공개할지 · 친구 족보를 여기에 합칠지"""
    if db().get_document(doc_id) is None:
        raise HTTPException(404, "강의자료가 없습니다.")
    return db().set_doc_friend_flags(doc_id, body.share, body.merge)


def _friend_or_403(me: str, other: str) -> dict:
    friend = next((f for f in db().friend_rows(me) if f["id"] == other and f["status"] == "accepted"), None)
    if friend is None:
        raise HTTPException(404, "친구가 아니에요.")
    return friend


@app.get("/friends/{other}/timetable")
def friend_timetable(other: str):
    """친구 시간표 보기 (친구가 공개했을 때만)"""
    me = _me()
    friend = _friend_or_403(me, other)
    theirs = _shares_with(other, me)
    if not theirs or not theirs.get("share_timetable", True):
        raise HTTPException(403, f"{friend['name']}님이 시간표를 비공개로 해 뒀어요.")
    token = auth.CURRENT_USER.set(other)
    try:
        return {"name": friend["name"], "classes": [{k: c[k] for k in ("course", "weekday", "start", "end", "place")}
                                                    for c in db().list_classes()]}
    finally:
        auth.CURRENT_USER.reset(token)


# 관리자 페이지 (#/admin): 사용자 계정과 따로 관리자 비밀번호로 들어간다.
# 처음 한 번은 초대 코드로 관리자 비밀번호를 정한다 (정한 뒤에는 잠긴다). 서버 환경 변수 ADMIN_PASSWORD 가 있으면 그것을 쓴다.


class AdminLogin(BaseModel):
    password: str
    invite: str = ""


def _admin_hash() -> str | None:
    env = os.environ.get("ADMIN_PASSWORD", "").strip()
    return ("env:" + env) if env else db().get_setting("admin_hash")


def _admin_ok_password(password: str) -> bool:
    h = _admin_hash()
    if not h:
        return False
    if h.startswith("env:"):
        return secrets.compare_digest(password, h[4:])
    return auth.check_password(password, h)


def _admin(request: Request) -> None:
    token = request.cookies.get(auth.ADMIN_COOKIE)
    until = db().get_setting("admin_token:" + auth.token_hash(token)) if token else None
    if not until or float(until) < time.time():
        raise HTTPException(401, "관리자 로그인이 필요해요.")


def _admin_session(request: Request) -> JSONResponse:
    token = secrets.token_urlsafe(32)
    until = time.time() + auth.ADMIN_HOURS * 3600
    db().set_setting("admin_token:" + auth.token_hash(token), str(until))
    res = JSONResponse({"set": True, "logged_in": True})
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    res.set_cookie(auth.ADMIN_COOKIE, token, max_age=auth.ADMIN_HOURS * 3600, httponly=True, samesite="strict", secure=secure, path="/")
    return res


@app.get("/admin/status")
def admin_status(request: Request):
    try:
        _admin(request)
        logged = True
    except HTTPException:
        logged = False
    return {"set": bool(_admin_hash()), "logged_in": logged, "auth": auth.enabled()}


@app.post("/admin/setup")
def admin_setup(body: AdminLogin, request: Request):
    """처음 한 번: 초대 코드로 관리자 비밀번호를 정한다"""
    if _admin_hash():
        raise HTTPException(409, "관리자 비밀번호가 이미 있어요. 로그인해 주세요.")
    if _too_many(request):
        raise HTTPException(429, "여러 번 틀려서 10분 동안 막혔어요.")
    if not auth.invite_ok(body.invite, db().get_setting("invite_code")):
        _login_fails.setdefault(_client(request), []).append(time.time())
        raise HTTPException(403, "초대 코드가 맞지 않아요.")
    if len(body.password) < 8:
        raise HTTPException(400, "관리자 비밀번호는 8자 이상으로 해 주세요.")
    db().set_setting("admin_hash", auth.hash_password(body.password))
    return _admin_session(request)


@app.post("/admin/login")
def admin_login(body: AdminLogin, request: Request):
    now = time.time()
    everyone = [t for t in _login_fails.get("admin:*", []) if t > now - ADMIN_GLOBAL[1]]
    _login_fails["admin:*"] = everyone
    if _too_many(request, "admin:", *ADMIN_LIMIT) or len(everyone) >= ADMIN_GLOBAL[0]:
        raise HTTPException(429, "여러 번 틀려서 관리자 로그인이 잠시 잠겼어요. 15분 뒤에 다시 해 주세요.")
    if not _admin_ok_password(body.password):
        _login_fails.setdefault("admin:" + _client(request), []).append(now)
        everyone.append(now)
        raise HTTPException(401, "관리자 비밀번호가 맞지 않아요.")
    return _admin_session(request)


@app.post("/admin/logout")
def admin_logout(request: Request):
    token = request.cookies.get(auth.ADMIN_COOKIE)
    if token:
        db().set_setting("admin_token:" + auth.token_hash(token), None)
    res = JSONResponse({"ok": True})
    res.delete_cookie(auth.ADMIN_COOKIE, path="/")
    return res


class AdminPassword(BaseModel):
    current: str
    password: str


@app.post("/admin/password")
def admin_password(body: AdminPassword, request: Request):
    _admin(request)
    if os.environ.get("ADMIN_PASSWORD"):
        raise HTTPException(400, "이 서버는 관리자 비밀번호를 서버 설정(ADMIN_PASSWORD)으로 정해 두었어요.")
    if not _admin_ok_password(body.current):
        raise HTTPException(401, "지금 관리자 비밀번호가 맞지 않아요.")
    if len(body.password) < 8:
        raise HTTPException(400, "관리자 비밀번호는 8자 이상으로 해 주세요.")
    db().set_setting("admin_hash", auth.hash_password(body.password))
    return {"ok": True}


@app.get("/admin/overview")
async def admin_overview(request: Request):
    """서버 상태 · AI 진단 · 사람 목록"""
    _admin(request)
    disk = shutil.disk_usage(os.path.dirname(os.path.abspath(settings.upload_dir)) or "/")
    mem_total = mem_avail = 0
    try:
        with open("/proc/meminfo") as f:
            info = dict(line.split(":", 1) for line in f)
        mem_total = int(info["MemTotal"].split()[0]) // 1024
        mem_avail = int(info["MemAvailable"].split()[0]) // 1024
    except (OSError, KeyError, ValueError):
        pass
    version = ""
    for path in ("/opt/lune/app/VERSION", os.path.join(os.path.dirname(__file__), "..", "..", "VERSION")):
        try:
            version = open(path).read().strip()
            break
        except OSError:
            continue
    return {"server": {"version": version, "disk_free_gb": round(disk.free / 1e9, 1), "disk_total_gb": round(disk.total / 1e9, 1),
                       "mem_total_mb": mem_total, "mem_avail_mb": mem_avail},
            "ai": await diag_ai(), "users": db().admin_users(),
            "invite_custom": bool(db().get_setting("invite_code")), "mail": (mailer.account(db()) or ("",))[0]}


# 자동 백업 (app/backup.py): 하루 한 번 허깅페이스 비공개 데이터셋에


async def _backup_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        try:
            if backup.due(db()):
                await asyncio.to_thread(backup.run, db(), settings.upload_dir)
                log.info("자동 백업 끝")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("자동 백업 실패")


class BackupSetting(BaseModel):
    token: str
    repo: str


async def _a1_loop() -> None:
    """큰 서버 자동 만들기: 켜 두면 2분마다 한 번 (관리자 페이지)"""
    while True:
        await asyncio.sleep(30)
        try:
            if a1retry.due(db()):
                await asyncio.to_thread(a1retry.try_once, db())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("큰 서버 만들기 시도 실패: %s", exc)
            a1retry._save(db(), message=f"설정을 확인해 주세요: {str(exc)[:160]}", at=time.time())


class A1Settings(BaseModel):
    user: str = ""          # 오라클 API 키 '설정 파일 미리보기'의 값들
    fingerprint: str = ""
    tenancy: str = ""
    region: str = ""
    key: str = ""           # 개인 키 (.pem 내용 전체)
    init: str = ""          # 새 서버 설치 스크립트 (lune-init.txt 내용 전체, 키 채운 것)
    enabled: bool = True


@app.get("/admin/a1")
def a1_status(request: Request):
    _admin(request)
    cfg = json.loads(db().get_setting("a1_config") or "{}")
    return {**a1retry.status(db()), "configured": a1retry.configured(db()), "region": cfg.get("region", ""),
            "has_key": bool(cfg.get("key")), "has_init": bool(db().get_setting("a1_init"))}


@app.put("/admin/a1")
def a1_set(body: A1Settings, request: Request):
    """빈 칸은 예전 값을 그대로 둔다 (키를 다시 안 넣고 켜고 끄기만 할 수 있게)"""
    _admin(request)
    cfg = json.loads(db().get_setting("a1_config") or "{}")
    for k in ("user", "fingerprint", "tenancy", "region", "key"):
        v = getattr(body, k).strip()
        if k == "key" and "-----END" in v:   # 오라클이 키 파일 끝에 붙이는 'OCI_API_KEY' 이름표 등은 뺀다
            end = v.index("-----END")
            v = v[: v.index("-----", end + 8) + 5]
        if v:
            cfg[k] = v
    if body.key.strip() and "PRIVATE KEY" not in body.key:
        raise HTTPException(400, "개인 키는 '-----BEGIN PRIVATE KEY-----'로 시작하는 .pem 파일 내용 전체를 넣어 주세요.")
    db().set_setting("a1_config", json.dumps(cfg))
    if body.init.strip():
        if "GROQ_API_KEY=" not in body.init or "PUT_" in body.init.split("MIGRATE_CODE")[0]:
            raise HTTPException(400, "설치 스크립트에 키가 다 채워졌는지 확인해 주세요 (PUT_… 칸이 남아 있어요).")
        db().set_setting("a1_init", body.init)
    if body.enabled and not all(cfg.get(k) for k in ("user", "fingerprint", "tenancy", "region", "key")):
        raise HTTPException(400, "오라클 API 키 설정 값 다섯 개를 모두 넣어 주세요.")
    a1retry._save(db(), enabled=body.enabled, at=0, **({"message": "곧 첫 시도를 해요"} if body.enabled else {"message": "멈췄어요"}))
    return a1_status(request)


@app.post("/admin/a1/reset")
def a1_reset(request: Request):
    """만든 뒤 다시 처음부터 (새 서버를 지웠을 때)"""
    _admin(request)
    db().set_setting("a1_status", None)
    return a1_status(request)


@app.get("/admin/backup")
def backup_status(request: Request):
    _admin(request)
    return {"repo": db().get_setting("backup_repo") or "", "has_token": bool(db().get_setting("backup_token")),
            "last": json.loads(db().get_setting("backup_last") or "null"), "error": db().get_setting("backup_error") or "",
            "running": bool(getattr(app.state, "backup_running", False))}


@app.put("/admin/backup")
async def backup_setup(body: BackupSetting, request: Request):
    """허깅페이스 쓰기 토큰 + 저장소 이름 (예: 아이디/lune-backup). 저장하기 전에 토큰이 맞는지 확인한다"""
    _admin(request)
    repo, token = body.repo.strip(), body.token.strip()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise HTTPException(400, "저장소 이름은 '아이디/lune-backup' 처럼 적어 주세요.")
    try:
        from huggingface_hub import HfApi

        who = await asyncio.to_thread(lambda: HfApi(token=token).whoami())
    except Exception as exc:
        raise HTTPException(400, "허깅페이스 토큰이 맞지 않아요. 'Write' 권한 토큰인지 확인해 주세요.") from exc
    db().set_setting("backup_token", token)
    db().set_setting("backup_repo", repo)
    return {"repo": repo, "user": who.get("name", "")}


@app.post("/admin/backup/run", status_code=202)
async def backup_now(request: Request, background: BackgroundTasks):
    _admin(request)
    if not db().get_setting("backup_token"):
        raise HTTPException(400, "먼저 백업 설정을 넣어 주세요.")
    if getattr(app.state, "backup_running", False):
        return {"running": True}

    async def go():
        app.state.backup_running = True
        try:
            await asyncio.to_thread(backup.run, db(), settings.upload_dir)
        except Exception:
            log.exception("백업 실패")
        finally:
            app.state.backup_running = False

    background.add_task(go)
    return {"running": True}


class InviteChange(BaseModel):
    code: str


@app.put("/admin/invite")
def admin_invite(body: InviteChange, request: Request):
    """초대 코드 바꾸기 (새로 가입할 때만 쓰인다. 이미 가입한 사람은 그대로)"""
    _admin(request)
    code = body.code.strip()
    if len(code) < 6:
        raise HTTPException(400, "초대 코드는 6자 이상으로 해 주세요.")
    db().set_setting("invite_code", code)
    return {"ok": True}


@app.post("/admin/users/{user_id}/logout")
def admin_logout_user(user_id: str, request: Request):
    """그 사람의 모든 기기 로그인 끊기"""
    _admin(request)
    db().drop_logins(user_id)
    return {"ok": True}


# 서버 옮기기: 서버 주인이 '옮기기 코드'를 받아 새 서버의 설치 스크립트에 넣으면, 새 서버가 이 서버의 자료를 통째로 가져간다
# 코드는 파일에 둔다 (서버가 1시간마다 업데이트로 다시 켜져도 남게). 새 서버 자리가 날 때까지 오래 걸릴 수 있어 2일 동안 쓴다
MIGRATE_DAYS = 2


def _migrate_file() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.upload_dir)), "migrate-code.json")


def _migrate_load() -> dict:
    try:
        with open(_migrate_file(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


@app.post("/admin/migrate")
def migrate_code(request: Request):
    """옮기기 코드 (2일 동안 쓸 수 있다). 관리자만"""
    _admin(request)
    code = secrets.token_urlsafe(18)
    saved = {"code": code, "until": time.time() + MIGRATE_DAYS * 86400}
    os.makedirs(os.path.dirname(_migrate_file()), exist_ok=True)
    with open(_migrate_file(), "w", encoding="utf-8") as f:
        json.dump(saved, f)
    os.chmod(_migrate_file(), 0o600)
    return saved


@app.get("/migrate/export")
def migrate_export(code: str, background: BackgroundTasks):
    """새 서버가 가져가는 자료 묶음: DB(로그인 표 빼고) + 올린 파일들(강의자료·녹음·사진) (tar.gz)"""
    import tarfile
    import tempfile

    saved = _migrate_load()
    if not saved or time.time() > saved.get("until", 0) or not secrets.compare_digest(code, saved.get("code", "")):
        raise HTTPException(403, "옮기기 코드가 맞지 않거나 시간이 지났어요.")
    tmp = tempfile.mkdtemp(prefix="lune-migrate-")
    db_copy = os.path.join(tmp, "lune.db")
    db().backup_to(db_copy)
    import sqlite3 as _sqlite
    with _sqlite.connect(db_copy) as c:   # 로그인 표는 옮기지 않는다 (새 서버에서 다시 로그인)
        c.execute("DELETE FROM logins")
    out = os.path.join(tmp, "lune-data.tar.gz")
    with tarfile.open(out, "w:gz") as tar:
        tar.add(db_copy, arcname=os.path.basename(settings.db_path))
        if os.path.isdir(settings.upload_dir):
            tar.add(settings.upload_dir, arcname=os.path.basename(settings.upload_dir.rstrip("/")))
    background.add_task(shutil.rmtree, tmp, True)
    return FileResponse(out, media_type="application/gzip", filename="lune-data.tar.gz")


@app.get("/diag/ai")
async def diag_ai():
    """AI 연결 진단 (로그인한 사람만): Groq 에 닿는지, 사진 읽는 모델이 있는지, 받아쓰기가 어디로 가는지. 키 값은 보여 주지 않는다"""
    import httpx

    out: dict = {"llm_mode": settings.llm_mode, "stt_mode": settings.stt_mode, "groq_key_set": bool(settings.groq_api_key)}
    if settings.groq_api_key:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get("https://api.groq.com/openai/v1/models",
                                     headers={"Authorization": f"Bearer {settings.groq_api_key}"})
            out["groq_status"] = r.status_code
            if r.status_code < 400:
                ids = [m.get("id", "") for m in r.json().get("data", [])]
                out["vision_models"] = [i for i in ids if re.search(r"vision|llama-4|scout|maverick|[-_]vl|pixtral|gemma-3", i, re.I)]
                out["whisper_models"] = [i for i in ids if "whisper" in i]
            else:
                out["groq_error"] = r.text[:200]
        except Exception as exc:
            out["groq_error"] = f"{type(exc).__name__}: {exc}"[:200]
    t = app.state.transcriber
    out["stt_engine"] = getattr(t, "engine", None)
    out["stt_local_used"] = getattr(t, "local_used", None)
    out["stt_last_error"] = getattr(t, "last_error", None)
    try:
        import onnxruntime  # noqa: F401
        out["ocr_runtime"] = True
    except ImportError:
        out["ocr_runtime"] = False
    return out


@app.get("/friends/jokbo")
def friends_jokbo():
    """족보 관리: 내 강의자료마다 함께 합쳐지는 친구와, 파일로 받은 족보"""
    me = _me()
    out = []
    for d in db().list_documents():
        if not db().session_ids(d["id"]):
            continue
        friends = [s["nickname"] for s in _friend_sheets(d["id"])]
        files = [{"id": s["id"], "nickname": s["nickname"], "created_at": s["created_at"]} for s in db().list_shared(d["id"])]
        out.append({"doc_id": d["id"], "title": d["title"], "course": d.get("course") or "", "friends": friends, "files": files,
                    **{f"friend_{k}": v for k, v in db().doc_friend_flags(d["id"]).items()}})
    out.sort(key=lambda x: (-(len(x["friends"]) + len(x["files"])), x["title"]))
    return {"docs": out}


@app.get("/friends")
def list_friends():
    me = _me()
    rows = db().friend_rows(me)
    user = db().get_user(me) or {}
    courses = sorted({d.get("course") or "" for d in db().list_documents()} - {""})
    mine = {_course_key(c): c for c in [c["course"] for c in db().list_classes()] + courses}  # 강의자료 이름을 먼저
    for r in rows:
        if r["status"] == "accepted":
            theirs = _shares_with(r["id"], me) or {}
            r.update(db().pair(me, r["id"]), their_jokbo=bool(theirs.get("share_jokbo")),
                     their_timetable=bool(theirs.get("share_timetable")))
            r["same_courses"] = sorted({mine[k] for k in _visible_courses(r["id"], theirs) if k in mine})
    return {"me": {"name": user.get("name", ""), "code": db().friend_code(me), "prefs": user.get("prefs", {}), "courses": courses},
            "friends": [r for r in rows if r["status"] == "accepted"],
            "incoming": [r for r in rows if r["status"] == "pending" and not r["mine"]],
            "outgoing": [r for r in rows if r["status"] == "pending" and r["mine"]]}


@app.post("/friends")
def add_friend(body: FriendRequest):
    me = _me()
    other = db().user_by_code(body.code)
    if other is None:
        raise HTTPException(404, "그 코드의 친구를 찾지 못했어요. 코드를 다시 확인해 주세요.")
    if other["id"] == me:
        raise HTTPException(400, "내 코드예요. 친구의 코드를 넣어 주세요.")
    if not (db().get_user(other["id"]) or {}).get("prefs", {}).get("allow_requests", True) and me not in [
            r["id"] for r in db().friend_rows(other["id"])]:
        raise HTTPException(403, f"{other['name']}님은 지금 친구 신청을 받지 않아요.")
    status = db().request_friend(me, other["id"])
    return {"status": status, "name": other["name"]}


@app.post("/friends/{other}/accept")
def accept_friend(other: str):
    if not db().accept_friend(_me(), other):
        raise HTTPException(404, "받은 친구 신청이 없어요.")
    return list_friends()


@app.delete("/friends/{other}", status_code=204)
def remove_friend(other: str):
    if not db().remove_friend(_me(), other):
        raise HTTPException(404, "친구가 아니에요.")


@app.get("/documents/{doc_id}/share")
def export_share(doc_id: str, nickname: str = ""):
    sheet = _jokbo(doc_id, with_friends=False)
    body = _share_body(sheet)
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
