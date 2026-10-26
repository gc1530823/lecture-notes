"""WebSocket 강의 세션 하나의 상태: 받아쓰기를 모아 두었다가 필기를 만든다."""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable

import anthropic

from .config import settings
from .db import Database
from .llm import ANNOTATION_TYPES, LLM, LLMError

log = logging.getLogger(__name__)

Send = Callable[[dict], Awaitable[None]]


class LiveSession:
    def __init__(self, db: Database, llm: LLM, session: dict, send: Send):
        self.db = db
        self.llm = llm
        self.session_id = session["id"]
        self.document_id = session["document_id"]
        self.send = send

        self.page: dict | None = None
        # 아직 필기로 만들지 않은 받아쓰기: (페이지, 시작 시각, 문장 목록)
        self.pending_page: dict | None = None
        self.pending_start_ms = 0
        self.pending_texts: list[str] = []
        self.pending_since = 0.0

        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    async def handle(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "page_view":
            await self._on_page_view(int(message["page"]))
        elif kind == "transcript_final":
            await self._on_transcript(message)
        elif kind == "flush":
            self._schedule_flush()
        else:
            await self.send({"type": "error", "message": f"알 수 없는 메시지: {kind}"})

    async def tick(self) -> None:
        """주기적으로 불려서, 오래 기다린 받아쓰기가 있으면 필기를 만든다."""
        if self.pending_texts and time.monotonic() - self.pending_since >= settings.max_wait_seconds:
            self._schedule_flush()

    async def close(self) -> None:
        self._schedule_flush()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _on_page_view(self, page_no: int) -> None:
        page = self.db.get_page(self.document_id, page_no)
        if page is None:
            await self.send({"type": "error", "message": f"{page_no}페이지가 없습니다."})
            return
        if self.page and self.page["id"] != page["id"]:
            # 페이지가 바뀌면 이전 페이지에 쌓인 받아쓰기를 먼저 필기로 만든다
            self._schedule_flush()
        self.page = page

    async def _on_transcript(self, message: dict) -> None:
        text = str(message.get("text", "")).strip()
        if not text:
            return
        start_ms = int(message.get("start_ms", 0))
        end_ms = int(message.get("end_ms", start_ms))
        page_id = self.page["id"] if self.page else None
        self.db.add_segment(self.session_id, page_id, start_ms, end_ms, text)
        if self.page is None:
            return

        if not self.pending_texts:
            self.pending_page = self.page
            self.pending_start_ms = start_ms
            self.pending_since = time.monotonic()
        self.pending_texts.append(text)

        if sum(len(t) for t in self.pending_texts) >= settings.min_chars_per_call:
            self._schedule_flush()

    def _schedule_flush(self) -> None:
        if not self.pending_texts or self.pending_page is None:
            return
        batch = (self.pending_page, self.pending_start_ms, " ".join(self.pending_texts))
        self.pending_page, self.pending_texts = None, []
        task = asyncio.create_task(self._annotate(*batch))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _annotate(self, page: dict, start_ms: int, transcript: str) -> None:
        # 같은 세션의 호출은 한 번에 하나씩: 앞 호출의 필기를 "이미 쓴 필기"로 넘기기 위해
        async with self._lock:
            blocks = self.db.get_blocks(page["id"])
            existing = self.db.list_annotations(self.session_id, page["id"])
            try:
                results = await self.llm.annotate(blocks, existing, transcript)
            except anthropic.RateLimitError:
                log.warning("필기 생성: 요청 한도 초과")
                await self.send({"type": "error", "message": "요청이 많아 잠시 필기를 건너뜁니다."})
                return
            except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError) as exc:
                log.exception("필기 생성 실패")
                await self.send({"type": "error", "message": f"필기 생성 실패: {exc}"})
                return

            block_ids = {b["id"] for b in blocks}
            for item in results:
                text = item.get("text", "").strip()
                if not text or item.get("type") not in ANNOTATION_TYPES:
                    continue
                block_id = item.get("block_id")
                annotation = self.db.add_annotation(
                    self.session_id,
                    page["id"],
                    block_id if block_id in block_ids else None,
                    item["type"],
                    text,
                    start_ms,
                )
                await self.send({"type": "annotation_added", "annotation": annotation})
