"""SQLite 저장소. MVP용이며, 대규모 단계에서는 PostgreSQL + pgvector로 옮긴다."""

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any

from .auth import CURRENT_USER


def _me() -> str:
    """지금 요청한 사람 (혼자 쓸 때는 '')"""
    return CURRENT_USER.get() or ""


def _mine(owner: str) -> bool:
    user = CURRENT_USER.get()
    return user is None or owner == user


def _owner_clause(column: str = "owner") -> tuple[str, tuple]:
    user = CURRENT_USER.get()
    return (f" WHERE {column} = ?", (user,)) if user is not None else ("", ())

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    keywords TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(id),
    page_no INTEGER NOT NULL,
    width REAL NOT NULL,
    height REAL NOT NULL,
    text TEXT NOT NULL,
    UNIQUE (document_id, page_no)
);
CREATE TABLE IF NOT EXISTS blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER NOT NULL REFERENCES pages(id),
    x REAL NOT NULL, y REAL NOT NULL, w REAL NOT NULL, h REAL NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    status TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL
);
CREATE TABLE IF NOT EXISTS transcript_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    page_id INTEGER REFERENCES pages(id),
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    page_id INTEGER NOT NULL REFERENCES pages(id),
    block_id INTEGER REFERENCES blocks(id),
    type TEXT NOT NULL,
    text TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    edited_by_user INTEGER NOT NULL DEFAULT 0,
    pending INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS photos (
    -- 칠판·화이트보드 사진: 찍은 쪽, 그 사진으로 만든 필기
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    page_no INTEGER NOT NULL,
    annotation_id INTEGER,
    path TEXT NOT NULL,
    mime TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS shared (
    -- 함께 만드는 족보: 친구가 보내 준 족보 파일 (같은 강의자료끼리)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    nickname TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS quiz_sets (
    -- AI 퀴즈: AI가 강의를 공부하고 낸 문제 묶음과 학생 답·채점 (강의 하나 또는 강의자료 전체)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    session_id TEXT,
    body TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    -- 친구들과 함께 쓸 때 (INVITE_CODE): 이름 + 비밀번호(scrypt). 혼자 쓸 때는 비어 있다
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS logins (
    -- 로그인 표 (쿠키) 의 해시
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS classes (
    -- 시간표: 과목·요일(0=월 … 6=일)·시작·끝("HH:MM")·강의실
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course TEXT NOT NULL,
    weekday INTEGER NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    place TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS exams (
    -- 시험 D-day: 이름·날짜·범위(강의자료 id 목록)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    exam_date TEXT NOT NULL,
    doc_ids TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS marks (
    -- 수업 중 "모르겠다": 그 순간의 쪽과 시각. 설명은 나중에 AI가 채운다
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    page_no INTEGER NOT NULL,
    at_ms INTEGER NOT NULL,
    speech TEXT NOT NULL DEFAULT '',
    explanation TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    -- 망각 곡선 복습 일정 (카드 하나에 한 줄). 카드 내용은 플래시카드·예상 문제·모르겠다 설명에서 온다
    card_key TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    source TEXT NOT NULL,
    front TEXT NOT NULL,
    back TEXT NOT NULL,
    page_no INTEGER,
    ease REAL NOT NULL DEFAULT 2.5,
    interval REAL NOT NULL DEFAULT 0,
    reps INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    due_at REAL,
    last_at REAL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    -- 사용자가 AI 필기를 고친 기록: 우리 AI 학습 데이터를 바로잡는 데 쓴다 (scripts/export_training.py)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    annotation_id INTEGER NOT NULL,
    action TEXT NOT NULL,          -- edit | delete | move
    original_text TEXT NOT NULL,   -- AI가 처음 쓴 글 (같은 필기를 여러 번 고쳐도 처음 것)
    original_type TEXT NOT NULL,
    new_text TEXT,
    new_page_no INTEGER,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    page_id INTEGER REFERENCES pages(id),
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    instructions TEXT NOT NULL,
    due_text TEXT NOT NULL DEFAULT '',
    done INTEGER NOT NULL DEFAULT 0,
    draft TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS summaries (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    body TEXT NOT NULL
);

-- 시험 예상 문제 (강의자료 페이지마다). digest가 같으면(받아쓰기·필기가 그대로면) 다시 만들지 않는다
CREATE TABLE IF NOT EXISTS exam_questions (
    document_id TEXT NOT NULL REFERENCES documents(id),
    page_no INTEGER NOT NULL,
    digest TEXT NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (document_id, page_no)
);

-- 실시간 용어 사전: 강의 중에 처음 나온 전문용어와 뜻
CREATE TABLE IF NOT EXISTS glossary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    page_no INTEGER,
    term TEXT NOT NULL,
    definition TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    created_at REAL NOT NULL
);

-- 공부 도구 (플래시카드·개념 메모·마인드맵). digest가 같으면 다시 만들지 않는다
CREATE TABLE IF NOT EXISTS study_sets (
    session_id TEXT NOT NULL REFERENCES sessions(id),
    kind TEXT NOT NULL,
    digest TEXT NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (session_id, kind)
);

-- 정리 PDF용 페이지별 전체 정리. digest가 같으면(받아쓰기·필기가 그대로면) 다시 만들지 않는다
CREATE TABLE IF NOT EXISTS page_notes (
    session_id TEXT NOT NULL REFERENCES sessions(id),
    page_no INTEGER NOT NULL,
    digest TEXT NOT NULL,
    points TEXT NOT NULL,
    PRIMARY KEY (session_id, page_no)
);
"""


class Database:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._lock = threading.Lock()

    def _migrate(self) -> None:
        # 예전 DB 파일에 나중에 추가한 컬럼을 붙인다
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(annotations)")}
        if "pending" not in columns:
            self._conn.execute("ALTER TABLE annotations ADD COLUMN pending INTEGER NOT NULL DEFAULT 0")
            self._conn.commit()
        # kind: "slides" = 강의자료 PDF, "notebook" = 자료 없는 수업의 줄 노트 (주제마다 한 쪽)
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(documents)")}
        if "kind" not in columns:
            self._conn.execute("ALTER TABLE documents ADD COLUMN kind TEXT NOT NULL DEFAULT 'slides'")
            self._conn.commit()
        # course: 과목 이름 (자료를 과목별 폴더로 묶는다, 비면 "과목 없음")
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(documents)")}
        if "course" not in columns:
            self._conn.execute("ALTER TABLE documents ADD COLUMN course TEXT NOT NULL DEFAULT ''")
            self._conn.commit()
        # confidence: AI가 그 쪽이 맞다고 본 확신 (0~1, 사람이 쓰거나 확인하면 1). 낮으면 화면에 "확인 필요"
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(annotations)")}
        if "confidence" not in columns:
            self._conn.execute("ALTER TABLE annotations ADD COLUMN confidence REAL NOT NULL DEFAULT 1")
            self._conn.commit()
        # error: 정리에 실패한 이유 (화면에 보여 준다)
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(sessions)")}
        if "error" not in columns:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN error TEXT")
            self._conn.commit()
        # owner: 누구 자료인지 (친구들과 함께 쓸 때). 혼자 쓸 때·예전 자료는 '' (첫 가입자가 가져간다)
        for table in ("documents", "classes", "exams"):
            columns = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            if "owner" not in columns:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN owner TEXT NOT NULL DEFAULT ''")
                self._conn.commit()
        # question: "모르겠다" 표시를 복습 카드로 만들 때 AI가 쓴 앞면 질문
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(marks)")}
        if "question" not in columns:
            self._conn.execute("ALTER TABLE marks ADD COLUMN question TEXT")
            self._conn.commit()
        # loud: 목소리를 높여 말한 문장 (실시간 녹음에서 소리 크기로 잰다)
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(transcript_segments)")}
        if "loud" not in columns:
            self._conn.execute("ALTER TABLE transcript_segments ADD COLUMN loud INTEGER NOT NULL DEFAULT 0")
            self._conn.commit()

    def _query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def _write(self, sql: str, params: tuple = ()) -> int:
        with self._lock, self._conn:
            return self._conn.execute(sql, params).lastrowid

    # 문서

    # 노트 모드: 강의자료 없이 시작해, 교수님이 주제를 바꿀 때마다 쪽을 하나씩 늘린다 (쪽 text = 그 주제의 제목)
    NOTEBOOK_PAGE = (595.0, 842.0)  # A4 세로

    def create_notebook(self, title: str, kind: str = "notebook") -> str:
        doc_id = uuid.uuid4().hex
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO documents (id, title, page_count, keywords, created_at, kind, owner) VALUES (?, ?, 1, '[]', ?, ?, ?)",
                (doc_id, title, time.time(), kind, _me()),
            )
            self._conn.execute("INSERT INTO pages (document_id, page_no, width, height, text) VALUES (?, 1, ?, ?, '')",
                               (doc_id, *self.NOTEBOOK_PAGE))
        return doc_id

    def add_notebook_page(self, doc_id: str) -> dict:
        with self._lock, self._conn:
            no = self._conn.execute("SELECT COALESCE(MAX(page_no), 0) + 1 FROM pages WHERE document_id = ?",
                                    (doc_id,)).fetchone()[0]
            self._conn.execute("INSERT INTO pages (document_id, page_no, width, height, text) VALUES (?, ?, ?, ?, '')",
                               (doc_id, no, *self.NOTEBOOK_PAGE))
            self._conn.execute("UPDATE documents SET page_count = ? WHERE id = ?", (no, doc_id))
        return self._query("SELECT * FROM pages WHERE document_id = ? AND page_no = ?", (doc_id, no))[0]

    def set_course(self, doc_id: str, course: str) -> None:
        self._write("UPDATE documents SET course = ? WHERE id = ?", (course, doc_id))

    def rename_document(self, doc_id: str, title: str) -> None:
        self._write("UPDATE documents SET title = ? WHERE id = ?", (title, doc_id))

    def replace_blocks(self, page_id: int, text: str, blocks: list[dict]) -> None:
        """스캔본 쪽: 글자를 읽어 낸 뒤 쪽 글과 문단을 바꾼다."""
        with self._lock, self._conn:
            self._conn.execute("UPDATE pages SET text = ? WHERE id = ?", (text, page_id))
            self._conn.execute("DELETE FROM blocks WHERE page_id = ?", (page_id,))
            self._conn.executemany("INSERT INTO blocks (page_id, x, y, w, h, text) VALUES (?, ?, ?, ?, ?, ?)",
                                   [(page_id, b["x"], b["y"], b["w"], b["h"], b["text"]) for b in blocks])

    def mark_user_annotation(self, ann_id: int) -> None:
        self._write("UPDATE annotations SET edited_by_user = 1, confidence = 1 WHERE id = ?", (ann_id,))

    def set_confidence(self, ann_id: int, confidence: float) -> None:
        self._write("UPDATE annotations SET confidence = ? WHERE id = ?", (round(confidence, 3), ann_id))

    def review_annotation(self, ann_id: int, text: str | None = None, page_id: int | None = None, block_id: int | None = None,
                          delete: bool = False) -> None:
        """강의 뒤 AI가 다시 확인해 바로잡은 것 (사용자가 고친 것이 아니므로 feedback·edited_by_user는 건드리지 않는다)."""
        if delete:
            self._write("DELETE FROM annotations WHERE id = ? AND edited_by_user = 0", (ann_id,))
        elif text is not None:
            self._write("UPDATE annotations SET text = ?, confidence = 0.9 WHERE id = ? AND edited_by_user = 0", (text, ann_id))
        elif page_id is not None:
            self._write("UPDATE annotations SET page_id = ?, block_id = ?, confidence = 0.9 WHERE id = ? AND edited_by_user = 0",
                        (page_id, block_id, ann_id))

    def confirm_annotation(self, ann_id: int) -> dict | None:
        """사용자가 "맞아요"를 눌렀다: 확신 1로, 학습 데이터에는 '확인됨'으로 남긴다."""
        before = self.get_annotation(ann_id)
        if before is None:
            return None
        self._write("""INSERT INTO feedback (session_id, annotation_id, action, original_text, original_type, new_text, new_page_no, created_at)
                       VALUES (?, ?, 'confirm', ?, ?, NULL, ?, ?)""",
                    (before["session_id"], ann_id, before["text"], before["type"], before["page_no"], time.time()))
        self.set_confidence(ann_id, 1.0)
        return self.get_annotation(ann_id)

    def search(self, query: str, limit: int = 60) -> list[dict]:
        """모든 강의에서 찾기: 필기·교수님 말·용어·슬라이드 글. 최근 강의부터."""
        like = f"%{query}%"
        user = CURRENT_USER.get()
        own, mine = (" AND d.owner = ?", (user,)) if user is not None else ("", ())
        out = []
        out += [{**r, "kind": "note"} for r in self._query(
            """SELECT a.text, a.type AS note_type, a.start_ms, p.page_no, s.id AS session_id, d.id AS doc_id, d.title, d.course, s.started_at
               FROM annotations a JOIN pages p ON p.id = a.page_id JOIN sessions s ON s.id = a.session_id JOIN documents d ON d.id = s.document_id
               WHERE a.text LIKE ?""" + own + """ ORDER BY s.started_at DESC LIMIT ?""", (like, *mine, limit))]
        out += [{**r, "kind": "term"} for r in self._query(
            """SELECT g.term || ' — ' || g.definition AS text, g.start_ms, g.page_no, s.id AS session_id, d.id AS doc_id, d.title, d.course, s.started_at
               FROM glossary g JOIN sessions s ON s.id = g.session_id JOIN documents d ON d.id = s.document_id
               WHERE (g.term LIKE ? OR g.definition LIKE ?)""" + own + """ ORDER BY s.started_at DESC LIMIT ?""", (like, like, *mine, limit))]
        out += [{**r, "kind": "speech"} for r in self._query(
            """SELECT t.text, t.start_ms, p.page_no, s.id AS session_id, d.id AS doc_id, d.title, d.course, s.started_at
               FROM transcript_segments t LEFT JOIN pages p ON p.id = t.page_id JOIN sessions s ON s.id = t.session_id
               JOIN documents d ON d.id = s.document_id
               WHERE t.text LIKE ?""" + own + """ ORDER BY s.started_at DESC, t.start_ms LIMIT ?""", (like, *mine, limit))]
        out += [{**r, "kind": "slide"} for r in self._query(
            """SELECT p.text, p.page_no, d.id AS doc_id, d.title, d.course, d.created_at AS started_at
               FROM pages p JOIN documents d ON d.id = p.document_id WHERE p.text LIKE ?""" + own + """ ORDER BY d.created_at DESC LIMIT ?""",
            (like, *mine, limit))]
        return out

    def set_page_text(self, page_id: int, text: str) -> None:
        self._write("UPDATE pages SET text = ? WHERE id = ?", (text, page_id))

    def create_document(self, title: str, pages: list[dict], keywords: list[str]) -> str:
        doc_id = uuid.uuid4().hex
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO documents (id, title, page_count, keywords, created_at, owner) VALUES (?, ?, ?, ?, ?, ?)",
                (doc_id, title, len(pages), json.dumps(keywords, ensure_ascii=False), time.time(), _me()),
            )
            for page in pages:
                page_id = self._conn.execute(
                    "INSERT INTO pages (document_id, page_no, width, height, text) VALUES (?, ?, ?, ?, ?)",
                    (doc_id, page["page_no"], page["width"], page["height"], page["text"]),
                ).lastrowid
                self._conn.executemany(
                    "INSERT INTO blocks (page_id, x, y, w, h, text) VALUES (?, ?, ?, ?, ?, ?)",
                    [(page_id, b["x"], b["y"], b["w"], b["h"], b["text"]) for b in page["blocks"]],
                )
        return doc_id

    def list_documents(self) -> list[dict]:
        """강의자료 목록 (최근 것부터)과 각 자료의 강의 목록"""
        user = CURRENT_USER.get()
        docs = self._query("SELECT id, title, page_count, created_at, kind, course FROM documents"
                           + (" WHERE owner = ?" if user is not None else "") + " ORDER BY created_at DESC",
                           (user,) if user is not None else ())
        for doc in docs:
            doc["sessions"] = self._query(
                "SELECT id, status, started_at FROM sessions WHERE document_id = ? ORDER BY started_at DESC",
                (doc["id"],),
            )
        return docs

    def reset_for_renote(self, session_id: str, notebook: bool) -> list[dict]:
        """필기 다시 만들기 준비: AI 필기·받아쓰기·요약·용어·퀴즈를 지우고, 지우기 전 받아쓰기를 돌려준다.
        사람이 쓰거나 고친 필기, 사진 필기, 질문(qa)은 남긴다. 노트 수업이면 주제 쪽을 첫 쪽만 남기고 다시 나눈다."""
        segments = self.get_segments(session_id)
        with self._lock, self._conn:
            self._conn.execute("""DELETE FROM annotations WHERE session_id = ? AND edited_by_user = 0 AND type != 'qa'
                                  AND id NOT IN (SELECT annotation_id FROM photos WHERE annotation_id IS NOT NULL)""", (session_id,))
            for table in ("transcript_segments", "summaries", "page_notes", "study_sets", "glossary", "quiz_sets"):
                self._conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
            if notebook:
                doc_id = self._conn.execute("SELECT document_id FROM sessions WHERE id = ?", (session_id,)).fetchone()[0]
                pages = [r[0] for r in self._conn.execute("SELECT id FROM pages WHERE document_id = ? ORDER BY page_no", (doc_id,))]
                if pages:
                    first, rest = pages[0], pages[1:]
                    for pid in rest:
                        self._conn.execute("UPDATE annotations SET page_id = ? WHERE page_id = ?", (first, pid))
                        self._conn.execute("DELETE FROM blocks WHERE page_id = ?", (pid,))
                        self._conn.execute("DELETE FROM pages WHERE id = ?", (pid,))
                    self._conn.execute("UPDATE pages SET text = '' WHERE id = ?", (first,))
                    self._conn.execute("UPDATE documents SET page_count = 1 WHERE id = ?", (doc_id,))
        return segments

    def delete_session(self, session_id: str) -> None:
        """강의 하나와 그 강의에서 나온 것(받아쓰기·필기·요약·퀴즈·표시)을 지운다"""
        with self._lock, self._conn:
            for table in ("annotations", "transcript_segments", "tasks", "summaries", "page_notes", "study_sets", "glossary",
                          "feedback", "marks", "photos", "quiz_sets"):
                self._conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
            self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def delete_document(self, doc_id: str) -> list[str]:
        """강의자료와 그 강의들을 모두 지우고, 지운 강의 id를 돌려준다 (녹음·PDF 파일 정리용)."""
        with self._lock, self._conn:
            sessions = [r[0] for r in self._conn.execute("SELECT id FROM sessions WHERE document_id = ?", (doc_id,))]
            pages = [r[0] for r in self._conn.execute("SELECT id FROM pages WHERE document_id = ?", (doc_id,))]
            for sid in sessions:
                for table in ("annotations", "transcript_segments", "tasks", "summaries", "page_notes", "study_sets", "glossary", "feedback", "marks", "photos"):
                    self._conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (sid,))
            self._conn.execute("DELETE FROM sessions WHERE document_id = ?", (doc_id,))
            self._conn.execute("DELETE FROM exam_questions WHERE document_id = ?", (doc_id,))
            self._conn.execute("DELETE FROM reviews WHERE document_id = ?", (doc_id,))
            self._conn.execute("DELETE FROM shared WHERE document_id = ?", (doc_id,))
            self._conn.execute("DELETE FROM quiz_sets WHERE document_id = ?", (doc_id,))
            for pid in pages:
                self._conn.execute("DELETE FROM blocks WHERE page_id = ?", (pid,))
            self._conn.execute("DELETE FROM pages WHERE document_id = ?", (doc_id,))
            self._conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        return sessions

    def get_document(self, doc_id: str) -> dict | None:
        docs = self._query("SELECT * FROM documents WHERE id = ?", (doc_id,))
        if not docs or not _mine(docs[0]["owner"]):
            return None
        doc = docs[0]
        doc["keywords"] = json.loads(doc["keywords"])
        pages = self._query(
            "SELECT id, page_no, width, height, text FROM pages WHERE document_id = ? ORDER BY page_no", (doc_id,)
        )
        for page in pages:
            page["blocks"] = self.get_blocks(page["id"])
        doc["pages"] = pages
        return doc

    def get_page(self, doc_id: str, page_no: int) -> dict | None:
        rows = self._query("SELECT * FROM pages WHERE document_id = ? AND page_no = ?", (doc_id, page_no))
        return rows[0] if rows else None

    def list_pages(self, doc_id: str) -> list[dict]:
        return self._query("SELECT * FROM pages WHERE document_id = ? ORDER BY page_no", (doc_id,))

    def get_blocks(self, page_id: int) -> list[dict]:
        return self._query("SELECT id, x, y, w, h, text FROM blocks WHERE page_id = ? ORDER BY id", (page_id,))

    # 강의 세션

    def create_session(self, doc_id: str) -> str:
        session_id = uuid.uuid4().hex
        self._write(
            "INSERT INTO sessions (id, document_id, status, started_at) VALUES (?, ?, 'recording', ?)",
            (session_id, doc_id, time.time()),
        )
        return session_id

    def get_session(self, session_id: str) -> dict | None:
        rows = self._query("SELECT * FROM sessions WHERE id = ?", (session_id,))
        return rows[0] if rows else None

    def set_session_status(self, session_id: str, status: str, error: str | None = None) -> None:
        """error: 실패했을 때 화면에 보여 줄 이유 (다른 상태로 바뀌면 지운다)"""
        ended = time.time() if status == "processing" else None
        self._write(
            "UPDATE sessions SET status = ?, ended_at = COALESCE(ended_at, ?), error = ? WHERE id = ?",
            (status, ended, error if status == "failed" else None, session_id),
        )

    def add_segment(self, session_id: str, page_id: int | None, start_ms: int, end_ms: int, text: str, loud: bool = False) -> int:
        return self._write(
            "INSERT INTO transcript_segments (session_id, page_id, start_ms, end_ms, text, loud) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, page_id, start_ms, end_ms, text, int(loud)),
        )

    def refine_segments(self, session_id: str, segments: list[tuple[int, int, str]]) -> int:
        """강의 뒤 다시 받아쓴(더 정확한) 문장으로 바꾼다. 쪽·목소리 강조는 시각이 가장 가까운 예전 문장의 것을 물려받는다."""
        with self._lock, self._conn:
            old = self._conn.execute(
                "SELECT start_ms, page_id, loud FROM transcript_segments WHERE session_id = ? ORDER BY start_ms, id",
                (session_id,)).fetchall()
            if not old or not segments:
                return 0
            self._conn.execute("DELETE FROM transcript_segments WHERE session_id = ?", (session_id,))
            i = 0
            for start_ms, end_ms, text in segments:
                while i + 1 < len(old) and abs(old[i + 1]["start_ms"] - start_ms) <= abs(old[i]["start_ms"] - start_ms):
                    i += 1
                self._conn.execute(
                    "INSERT INTO transcript_segments (session_id, page_id, start_ms, end_ms, text, loud) VALUES (?, ?, ?, ?, ?, ?)",
                    (session_id, old[i]["page_id"], start_ms, end_ms, text, old[i]["loud"]))
        return len(segments)

    def get_segments(self, session_id: str) -> list[dict]:
        return self._query(
            """SELECT s.start_ms, s.end_ms, s.text, s.loud, p.page_no
               FROM transcript_segments s LEFT JOIN pages p ON p.id = s.page_id
               WHERE s.session_id = ? ORDER BY s.start_ms, s.id""",
            (session_id,),
        )

    # 필기

    def add_annotation(
        self, session_id: str, page_id: int, block_id: int | None, type_: str, text: str, start_ms: int,
        pending: bool = False,
    ) -> dict:
        ann_id = self._write(
            """INSERT INTO annotations (session_id, page_id, block_id, type, text, start_ms, pending, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, page_id, block_id, type_, text, start_ms, int(pending), time.time()),
        )
        return self.get_annotation(ann_id)

    def get_annotation(self, ann_id: int) -> dict | None:
        rows = self._query(
            """SELECT a.id, a.session_id, p.page_no, a.block_id, a.type, a.text, a.start_ms, a.edited_by_user, a.pending, a.confidence
               FROM annotations a JOIN pages p ON p.id = a.page_id WHERE a.id = ?""",
            (ann_id,),
        )
        if not rows:
            return None
        return _annotation(rows[0])

    def list_annotations(self, session_id: str, page_id: int | None = None) -> list[dict]:
        sql = """SELECT a.id, a.session_id, p.page_no, a.block_id, a.type, a.text, a.start_ms, a.edited_by_user, a.pending, a.confidence
                 FROM annotations a JOIN pages p ON p.id = a.page_id WHERE a.session_id = ?"""
        params: tuple = (session_id,)
        if page_id is not None:
            sql += " AND a.page_id = ?"
            params += (page_id,)
        return [_annotation(r) for r in self._query(sql + " ORDER BY a.id", params)]

    def _feedback(self, ann_id: int, action: str, new_text: str | None = None, new_page_no: int | None = None) -> None:
        before = self.get_annotation(ann_id)
        if before is None:
            return
        first = self._query("SELECT original_text, original_type FROM feedback WHERE annotation_id = ? ORDER BY id LIMIT 1", (ann_id,))
        original_text, original_type = (first[0]["original_text"], first[0]["original_type"]) if first else (before["text"], before["type"])
        self._write("""INSERT INTO feedback (session_id, annotation_id, action, original_text, original_type, new_text, new_page_no, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (before["session_id"], ann_id, action, original_text, original_type, new_text, new_page_no, time.time()))

    # 칠판 사진

    def add_photo(self, session_id: str, page_no: int, path: str, mime: str) -> int:
        return self._write("INSERT INTO photos (session_id, page_no, path, mime, created_at) VALUES (?, ?, ?, ?, ?)",
                           (session_id, page_no, path, mime, time.time()))

    def link_photo(self, photo_id: int, annotation_id: int) -> None:
        self._write("UPDATE photos SET annotation_id = ? WHERE id = ?", (annotation_id, photo_id))

    def get_photo(self, photo_id: int) -> dict | None:
        rows = self._query("SELECT * FROM photos WHERE id = ?", (photo_id,))
        return rows[0] if rows else None

    def photo_by_annotation(self, session_id: str) -> dict[int, int]:
        return {r["annotation_id"]: r["id"] for r in self._query(
            "SELECT id, annotation_id FROM photos WHERE session_id = ? AND annotation_id IS NOT NULL", (session_id,))}

    # 함께 만드는 족보

    def add_shared(self, document_id: str, nickname: str, body: dict) -> dict:
        shared_id = self._write("INSERT INTO shared (document_id, nickname, body, created_at) VALUES (?, ?, ?, ?)",
                                (document_id, nickname, json.dumps(body, ensure_ascii=False), time.time()))
        return {"id": shared_id, "nickname": nickname}

    def list_shared(self, document_id: str) -> list[dict]:
        return [{**r, "body": json.loads(r["body"])} for r in self._query(
            "SELECT * FROM shared WHERE document_id = ? ORDER BY id", (document_id,))]

    def delete_shared(self, shared_id: int) -> bool:
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM shared WHERE id = ?", (shared_id,)).rowcount > 0

    # 사용자 (친구들과 함께 쓸 때)

    def add_user(self, name: str, password_hash: str) -> dict:
        user_id = uuid.uuid4().hex
        with self._lock, self._conn:
            first = self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            self._conn.execute("INSERT INTO users (id, name, password, created_at) VALUES (?, ?, ?, ?)", (user_id, name, password_hash, time.time()))
            if first:  # 처음 가입한 사람(이 서버 주인)이 혼자 쓰던 자료를 가져간다
                for table in ("documents", "classes", "exams"):
                    self._conn.execute(f"UPDATE {table} SET owner = ? WHERE owner = ''", (user_id,))
        return {"id": user_id, "name": name}

    def user_by_name(self, name: str) -> dict | None:
        rows = self._query("SELECT * FROM users WHERE name = ?", (name,))
        return rows[0] if rows else None

    def add_login(self, token_hash: str, user_id: str, expires_at: float) -> None:
        self._write("INSERT INTO logins (token_hash, user_id, expires_at) VALUES (?, ?, ?)", (token_hash, user_id, expires_at))

    def login_user(self, token_hash: str) -> dict | None:
        rows = self._query("SELECT u.id, u.name FROM logins l JOIN users u ON u.id = l.user_id WHERE l.token_hash = ? AND l.expires_at > ?",
                           (token_hash, time.time()))
        return rows[0] if rows else None

    def delete_login(self, token_hash: str) -> None:
        self._write("DELETE FROM logins WHERE token_hash = ?", (token_hash,))

    def owner_of(self, path: str) -> tuple[bool, str | None]:
        from .auth import owner_of
        with self._lock:
            return owner_of(self._conn, path)

    # AI 퀴즈

    def add_quiz_set(self, document_id: str, session_id: str | None, body: dict) -> int:
        return self._write("INSERT INTO quiz_sets (document_id, session_id, body, created_at) VALUES (?, ?, ?, ?)",
                           (document_id, session_id, json.dumps(body, ensure_ascii=False), time.time()))

    def get_quiz_set(self, set_id: int) -> dict | None:
        rows = self._query("SELECT * FROM quiz_sets WHERE id = ?", (set_id,))
        return {**rows[0], "body": json.loads(rows[0]["body"])} if rows else None

    def save_quiz_set(self, set_id: int, body: dict) -> None:
        self._write("UPDATE quiz_sets SET body = ? WHERE id = ?", (json.dumps(body, ensure_ascii=False), set_id))

    # 시험 D-day

    def add_exam(self, title: str, exam_date: str, doc_ids: list[str]) -> dict:
        exam_id = self._write("INSERT INTO exams (title, exam_date, doc_ids, created_at, owner) VALUES (?, ?, ?, ?, ?)",
                              (title, exam_date, json.dumps(doc_ids), time.time(), _me()))
        return self.get_exam(exam_id)

    def get_exam(self, exam_id: int) -> dict | None:
        rows = self._query("SELECT * FROM exams WHERE id = ?", (exam_id,))
        if not rows or not _mine(rows[0]["owner"]):
            return None
        return {**rows[0], "doc_ids": json.loads(rows[0]["doc_ids"])}

    # 시간표

    def add_class(self, course: str, weekday: int, start: str, end: str, place: str) -> dict:
        class_id = self._write("INSERT INTO classes (course, weekday, start, end, place, owner) VALUES (?, ?, ?, ?, ?, ?)",
                               (course, weekday, start, end, place, _me()))
        return self._query("SELECT * FROM classes WHERE id = ?", (class_id,))[0]

    def list_classes(self) -> list[dict]:
        where, args = _owner_clause()
        return self._query("SELECT * FROM classes" + where + " ORDER BY weekday, start", args)

    def delete_class(self, class_id: int) -> bool:
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM classes WHERE id = ?", (class_id,)).rowcount > 0

    def list_exams(self) -> list[dict]:
        where, args = _owner_clause()
        return [{**r, "doc_ids": json.loads(r["doc_ids"])} for r in self._query("SELECT * FROM exams" + where + " ORDER BY exam_date", args)]

    def delete_exam(self, exam_id: int) -> bool:
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM exams WHERE id = ?", (exam_id,)).rowcount > 0

    # 모르겠다

    def add_mark(self, session_id: str, page_no: int, at_ms: int, speech: str) -> dict:
        mark_id = self._write("INSERT INTO marks (session_id, page_no, at_ms, speech, created_at) VALUES (?, ?, ?, ?, ?)",
                              (session_id, page_no, at_ms, speech, time.time()))
        return self.get_mark(mark_id)

    def get_mark(self, mark_id: int) -> dict | None:
        rows = self._query("SELECT * FROM marks WHERE id = ?", (mark_id,))
        return rows[0] if rows else None

    def list_marks(self, session_id: str) -> list[dict]:
        return self._query("SELECT * FROM marks WHERE session_id = ? ORDER BY at_ms", (session_id,))

    def set_mark_explanation(self, mark_id: int, text: str) -> dict | None:
        self._write("UPDATE marks SET explanation = ? WHERE id = ?", (text, mark_id))
        return self.get_mark(mark_id)

    def set_mark_question(self, mark_id: int, text: str) -> None:
        self._write("UPDATE marks SET question = ? WHERE id = ?", (text, mark_id))

    def delete_mark(self, mark_id: int) -> bool:
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM marks WHERE id = ?", (mark_id,)).rowcount > 0

    # 복습 일정

    def upsert_card(self, key: str, document_id: str, source: str, front: str, back: str, page_no: int | None) -> None:
        """새 카드는 일정 없이(due_at NULL) 넣고, 이미 있으면 내용만 고친다 (일정은 그대로)."""
        self._write("""INSERT INTO reviews (card_key, document_id, source, front, back, page_no, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(card_key) DO UPDATE SET front = excluded.front, back = excluded.back, page_no = excluded.page_no""",
                    (key, document_id, source, front, back, page_no, time.time()))

    def get_card(self, key: str) -> dict | None:
        rows = self._query("SELECT * FROM reviews WHERE card_key = ?", (key,))
        return rows[0] if rows else None

    def list_cards(self, document_id: str | None = None) -> list[dict]:
        if document_id:
            return self._query("SELECT * FROM reviews WHERE document_id = ?", (document_id,))
        where, args = _owner_clause("d.owner")
        return self._query("SELECT r.* FROM reviews r JOIN documents d ON d.id = r.document_id" + where, args)

    def save_card(self, card: dict) -> None:
        self._write("UPDATE reviews SET ease = ?, interval = ?, reps = ?, lapses = ?, due_at = ?, last_at = ? WHERE card_key = ?",
                    (card["ease"], card["interval"], card["reps"], card["lapses"], card["due_at"], card["last_at"], card["card_key"]))

    def list_feedback(self) -> list[dict]:
        return self._query("SELECT * FROM feedback ORDER BY id")

    def update_annotation(self, ann_id: int, text: str) -> dict | None:
        self._feedback(ann_id, "edit", new_text=text)
        self._write("UPDATE annotations SET text = ?, edited_by_user = 1 WHERE id = ?", (text, ann_id))
        return self.get_annotation(ann_id)

    def move_annotation(self, ann_id: int, page_id: int) -> dict | None:
        """보류함의 필기를 사용자가 고른 페이지에 붙인다 (문단 연결은 풀고 페이지 여백에 둔다)."""
        page = self._query("SELECT page_no FROM pages WHERE id = ?", (page_id,))
        self._feedback(ann_id, "move", new_page_no=page[0]["page_no"] if page else None)
        self._write("UPDATE annotations SET page_id = ?, block_id = NULL, pending = 0 WHERE id = ?", (page_id, ann_id))
        return self.get_annotation(ann_id)

    def delete_annotation(self, ann_id: int) -> bool:
        self._feedback(ann_id, "delete")
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM annotations WHERE id = ?", (ann_id,)).rowcount > 0

    # 과제

    def add_task(self, session_id: str, page_id: int | None, kind: str, title: str, instructions: str,
                 due_text: str) -> dict:
        task_id = self._write(
            """INSERT INTO tasks (session_id, page_id, kind, title, instructions, due_text, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, page_id, kind, title, instructions, due_text, time.time()),
        )
        return self.get_task(task_id)

    def get_task(self, task_id: int) -> dict | None:
        rows = self._query(
            """SELECT t.id, t.session_id, p.page_no, t.kind, t.title, t.instructions, t.due_text, t.done, t.draft
               FROM tasks t LEFT JOIN pages p ON p.id = t.page_id WHERE t.id = ?""",
            (task_id,),
        )
        return _task(rows[0]) if rows else None

    def list_tasks(self, session_id: str) -> list[dict]:
        rows = self._query(
            """SELECT t.id, t.session_id, p.page_no, t.kind, t.title, t.instructions, t.due_text, t.done, t.draft
               FROM tasks t LEFT JOIN pages p ON p.id = t.page_id WHERE t.session_id = ? ORDER BY t.id""",
            (session_id,),
        )
        return [_task(r) for r in rows]

    def set_task_done(self, task_id: int, done: bool) -> dict | None:
        self._write("UPDATE tasks SET done = ? WHERE id = ?", (int(done), task_id))
        return self.get_task(task_id)

    def save_task_draft(self, task_id: int, draft: dict) -> dict | None:
        self._write("UPDATE tasks SET draft = ? WHERE id = ?", (json.dumps(draft, ensure_ascii=False), task_id))
        return self.get_task(task_id)

    # 요약·퀴즈

    def save_summary(self, session_id: str, body: dict) -> None:
        self._write(
            "INSERT OR REPLACE INTO summaries (session_id, body) VALUES (?, ?)",
            (session_id, json.dumps(body, ensure_ascii=False)),
        )

    def get_page_notes(self, session_id: str, page_no: int, digest: str) -> dict | None:
        """{"points": [...], "speech": 교정한 받아쓰기 또는 None}"""
        rows = self._query("SELECT points FROM page_notes WHERE session_id = ? AND page_no = ? AND digest = ?",
                           (session_id, page_no, digest))
        if not rows:
            return None
        value = json.loads(rows[0]["points"])
        return {"points": value, "speech": None} if isinstance(value, list) else value

    def save_page_notes(self, session_id: str, page_no: int, digest: str, notes: dict) -> None:
        self._write("INSERT OR REPLACE INTO page_notes (session_id, page_no, digest, points) VALUES (?, ?, ?, ?)",
                    (session_id, page_no, digest, json.dumps(notes, ensure_ascii=False)))

    def add_term(self, session_id: str, page_no: int | None, term: str, definition: str, start_ms: int) -> dict:
        term_id = self._write(
            "INSERT INTO glossary (session_id, page_no, term, definition, start_ms, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, page_no, term, definition, start_ms, time.time()))
        return self._query("SELECT id, page_no, term, definition, start_ms FROM glossary WHERE id = ?", (term_id,))[0]

    def list_terms(self, session_id: str) -> list[dict]:
        return self._query("SELECT id, page_no, term, definition, start_ms FROM glossary WHERE session_id = ? ORDER BY id",
                           (session_id,))

    def get_study(self, session_id: str, kind: str) -> tuple[str, object] | None:
        rows = self._query("SELECT digest, body FROM study_sets WHERE session_id = ? AND kind = ?", (session_id, kind))
        return (rows[0]["digest"], json.loads(rows[0]["body"])) if rows else None

    def save_study(self, session_id: str, kind: str, digest: str, body: object) -> None:
        self._write("INSERT OR REPLACE INTO study_sets (session_id, kind, digest, body) VALUES (?, ?, ?, ?)",
                    (session_id, kind, digest, json.dumps(body, ensure_ascii=False)))

    def session_ids(self, doc_id: str) -> list[str]:
        return [r["id"] for r in self._query("SELECT id FROM sessions WHERE document_id = ? ORDER BY started_at",
                                             (doc_id,))]

    def get_exam_questions(self, doc_id: str, page_no: int) -> tuple[str, list[dict]] | None:
        rows = self._query("SELECT digest, body FROM exam_questions WHERE document_id = ? AND page_no = ?",
                           (doc_id, page_no))
        return (rows[0]["digest"], json.loads(rows[0]["body"])) if rows else None

    def save_exam_questions(self, doc_id: str, page_no: int, digest: str, questions: list[dict]) -> None:
        self._write("INSERT OR REPLACE INTO exam_questions (document_id, page_no, digest, body) VALUES (?, ?, ?, ?)",
                    (doc_id, page_no, digest, json.dumps(questions, ensure_ascii=False)))

    def get_summary(self, session_id: str) -> dict | None:
        rows = self._query("SELECT body FROM summaries WHERE session_id = ?", (session_id,))
        return json.loads(rows[0]["body"]) if rows else None


def _annotation(row: dict) -> dict:
    row["edited_by_user"] = bool(row["edited_by_user"])
    row["pending"] = bool(row["pending"])
    return row


def _task(row: dict) -> dict:
    row["done"] = bool(row["done"])
    row["draft"] = json.loads(row["draft"]) if row["draft"] else None
    return row
