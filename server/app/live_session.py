"""WebSocket 강의 세션 하나의 상태: 받아쓰기로 현재 페이지를 추정하고, 모아 두었다가 필기를 만든다."""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import anthropic

from .alignment import Estimate, PageIndex, PageTracker
from .config import settings
from .db import Database
from .llm import ANNOTATION_TYPES, LLM, LLMError

log = logging.getLogger(__name__)

Send = Callable[[dict], Awaitable[None]]


@dataclass
class Batch:
    """아직 필기로 만들지 않은 받아쓰기 묶음"""
    estimate: Estimate
    start_ms: int
    texts: list[str]
    since: float


class LiveSession:
    def __init__(self, db: Database, llm: LLM, session: dict, send: Send):
        self.db = db
        self.llm = llm
        self.session_id = session["id"]
        self.document_id = session["document_id"]
        self.send = send

        self.pages = db.list_pages(self.document_id)
        self.tracker = PageTracker(PageIndex([p["text"] for p in self.pages]))
        self.estimate: Estimate | None = None
        self.batch: Batch | None = None

        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    async def handle(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "page_view":
            await self._on_page_view(int(message["page"]), manual=not message.get("initial", False))
        elif kind == "transcript_final":
            await self._on_transcript(message)
        elif kind == "flush":
            self._schedule_flush()
        else:
            await self.send({"type": "error", "message": f"알 수 없는 메시지: {kind}"})

    async def tick(self) -> None:
        """주기적으로 불려서, 오래 기다린 받아쓰기가 있으면 필기를 만든다."""
        if self.batch and time.monotonic() - self.batch.since >= settings.max_wait_seconds:
            self._schedule_flush()

    async def close(self) -> None:
        self._schedule_flush()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _on_page_view(self, page_no: int, manual: bool) -> None:
        """신호 A: 사용자가 보고 있는 페이지 (manual = 직접 넘김)"""
        if not 1 <= page_no <= len(self.pages):
            await self.send({"type": "error", "message": f"{page_no}페이지가 없습니다."})
            return
        self.tracker.user_viewed(page_no, manual=manual)
        # 사용자가 넘기면 쌓아 둔 받아쓰기는 이전 페이지 것이므로 먼저 필기로 만든다
        if manual and self.batch and self.batch.estimate.page_no != page_no:
            self._schedule_flush()

    async def _on_transcript(self, message: dict) -> None:
        text = str(message.get("text", "")).strip()
        if not text or not self.pages:
            return
        start_ms = int(message.get("start_ms", 0))
        end_ms = int(message.get("end_ms", start_ms))

        estimate = self.tracker.observe(text, start_ms)
        moved = self.estimate is not None and estimate.page_no != self.estimate.page_no
        self.estimate = estimate
        page = self.pages[estimate.page_no - 1]
        self.db.add_segment(self.session_id, page["id"], start_ms, end_ms, text)
        await self.send({"type": "page_estimate", "page": estimate.page_no,
                         "confidence": round(estimate.confidence, 3)})

        # 추정 페이지가 바뀌면 이전 페이지에 쌓인 받아쓰기를 먼저 필기로 만든다
        if moved and self.batch:
            self._schedule_flush()

        if self.batch is None:
            self.batch = Batch(estimate, start_ms, [], time.monotonic())
        self.batch.estimate = estimate
        self.batch.texts.append(text)

        if sum(len(t) for t in self.batch.texts) >= settings.min_chars_per_call:
            self._schedule_flush()

    def _schedule_flush(self) -> None:
        if not self.batch or not self.batch.texts:
            return
        batch, self.batch = self.batch, None
        task = asyncio.create_task(self._annotate(batch))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _annotate(self, batch: Batch) -> None:
        # 같은 세션의 호출은 한 번에 하나씩: 앞 호출의 필기를 "이미 쓴 필기"로 넘기기 위해
        async with self._lock:
            confident = batch.estimate.confidence >= settings.page_confidence
            # 확신이 낮으면 후보 페이지 여러 장을 보여 주고 AI가 고르게 한다
            page_nos = [batch.estimate.page_no] if confident else batch.estimate.candidates
            candidates = []
            for no in page_nos:
                page = self.pages[no - 1]
                candidates.append({
                    "page_no": no,
                    "page_id": page["id"],
                    "blocks": self.db.get_blocks(page["id"]),
                    "existing": self.db.list_annotations(self.session_id, page["id"]),
                })
            transcript = " ".join(batch.texts)
            try:
                results = await self.llm.annotate(candidates, transcript)
            except anthropic.RateLimitError:
                log.warning("필기 생성: 요청 한도 초과")
                await self.send({"type": "error", "message": "요청이 많아 잠시 필기를 건너뜁니다."})
                return
            except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError) as exc:
                log.exception("필기 생성 실패")
                await self.send({"type": "error", "message": f"필기 생성 실패: {exc}"})
                return

            by_page = {c["page_no"]: c for c in candidates}
            for item in results:
                text = str(item.get("text", "")).strip()
                if not text or item.get("type") not in ANNOTATION_TYPES:
                    continue
                chosen = by_page.get(item.get("page_no"))
                if len(candidates) == 1:
                    chosen = candidates[0]
                # AI도 어느 페이지인지 확신하지 못하면 보류함에 넣고, 사용자가 붙일 페이지를 고르게 한다
                pending = chosen is None
                target = chosen or by_page[batch.estimate.page_no]
                block_ids = {b["id"] for b in target["blocks"]}
                block_id = item.get("block_id")
                annotation = self.db.add_annotation(
                    self.session_id,
                    target["page_id"],
                    block_id if not pending and block_id in block_ids else None,
                    item["type"],
                    text,
                    batch.start_ms,
                    pending=pending,
                )
                await self.send({"type": "annotation_added", "annotation": annotation})
