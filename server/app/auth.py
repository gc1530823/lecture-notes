"""로그인과 사람별 공간 (친구들과 함께 쓸 때).

- INVITE_CODE 를 정해 두면 켜진다. 초대 코드를 아는 사람만 이름과 비밀번호로 가입할 수 있고, 각자 자기 자료만 본다.
  INVITE_CODE 가 없으면(개발·Codespaces·테스트) 지금처럼 로그인 없이 혼자 쓴다.
- 비밀번호는 scrypt 로 바꿔 저장하고, 로그인하면 임의의 표를 쿠키(HttpOnly)로 준다 (DB에는 표의 해시만).
- 지금 누가 요청했는지는 CURRENT_USER 에 담기고, DB 가 그 사람 자료만 보여 준다 (db.py).
- 남의 자료 주소(/documents/남의 id …)는 서버 입구(middleware)에서 막는다 → 404
"""

import contextvars
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time

CURRENT_USER: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user", default=None)
COOKIE = "ln_session"
ADMIN_COOKIE = "ln_admin"   # 관리자 페이지 (사용자 계정과 따로)
ADMIN_HOURS = 12
LOGIN_DAYS = 180


def enabled() -> bool:
    return bool(os.environ.get("INVITE_CODE", "").strip())


def invite_ok(code: str, override: str | None = None) -> bool:
    """override: 관리자 페이지에서 바꾼 초대 코드 (있으면 그것이 이긴다)"""
    want = (override or os.environ.get("INVITE_CODE", "")).strip()
    return bool(want) and hmac.compare_digest(code.strip().encode(), want.encode())


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"{salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
        return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)), stored)
    except ValueError:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


NAME = re.compile(r"^[\w가-힣 .-]{1,20}$")

# 주소 → 그 자료의 주인을 찾는 SQL (첫 칸 = 주소의 id). 여기 없는 주소는 목록·만들기라서 DB가 사람별로 걸러 준다
_DOC = "SELECT owner FROM documents WHERE id = ?"
_SESSION = "SELECT d.owner FROM sessions s JOIN documents d ON d.id = s.document_id WHERE s.id = ?"
OWNER_SQL = {
    "documents": _DOC,
    "sessions": _SESSION,
    "annotations": "SELECT d.owner FROM annotations a JOIN sessions s ON s.id = a.session_id JOIN documents d ON d.id = s.document_id WHERE a.id = ?",
    "marks": "SELECT d.owner FROM marks m JOIN sessions s ON s.id = m.session_id JOIN documents d ON d.id = s.document_id WHERE m.id = ?",
    "photos": "SELECT d.owner FROM photos p JOIN sessions s ON s.id = p.session_id JOIN documents d ON d.id = s.document_id WHERE p.id = ?",
    "tasks": "SELECT d.owner FROM tasks t JOIN sessions s ON s.id = t.session_id JOIN documents d ON d.id = s.document_id WHERE t.id = ?",
    "quiz-sets": "SELECT d.owner FROM quiz_sets q JOIN documents d ON d.id = q.document_id WHERE q.id = ?",
    "shared": "SELECT d.owner FROM shared x JOIN documents d ON d.id = x.document_id WHERE x.id = ?",
    "review": "SELECT d.owner FROM reviews r JOIN documents d ON d.id = r.document_id WHERE r.card_key = ?",
    "exams": "SELECT owner FROM exams WHERE id = ?",
    "timetable": "SELECT owner FROM classes WHERE id = ?",
}
# 로그인 없이 열리는 곳: 화면 파일, 상태 확인, 로그인 자체
PUBLIC = ("/health", "/auth/", "/migrate/", "/admin/", "/web", "/app", "/favicon", "/icons", "/assets", "/manifest")


def is_public(path: str) -> bool:
    return path == "/" or any(path == p or path.startswith(p if p.endswith("/") else p + "/") or path == p for p in PUBLIC)


def owner_of(conn: sqlite3.Connection, path: str) -> tuple[bool, str | None]:
    """(주소가 특정 자료를 가리키는가, 그 자료의 주인). 자료가 없으면 주인 None (그다음은 화면이 404)"""
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or parts[0] not in OWNER_SQL:
        return False, None
    if parts[0] == "review" and parts[1] == "today":
        return False, None
    row = conn.execute(OWNER_SQL[parts[0]], (parts[1],)).fetchone()
    return True, (row[0] if row else None)


def now() -> float:
    return time.time()
