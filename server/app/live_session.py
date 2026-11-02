"""WebSocket 강의 세션 하나의 상태: 받아쓰기로 현재 페이지를 추정하고, 모아 두었다가 필기를 만든다."""

import asyncio
import re
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import anthropic

from .alignment import Estimate, PageIndex, PageTracker
from .config import settings
from .db import Database
from .llm import ANNOTATION_TYPES, LLM, TASK_KINDS, LLMError
from .text_fix import fix_terms, note_type, vocabulary
from .live_stt import LiveAudio
from .quick_notes import quick_note

log = logging.getLogger(__name__)

Send = Callable[[dict], Awaitable[None]]

# 교수님이 실제로 무언가를 시키는 말. 이런 말이 없으면 모델이 과제를 뽑아도 버린다 (작은 모델의 오탐지 방지).
DIRECTIVE = re.compile(
    r"(해|써|풀어|읽어|정리해|공부해|준비해|만들어|찾아)\s*(오|와|보|봐)\s*(세요|요|라)|내세요|제출|과제|숙제|"
    r"레포트|리포트|발표|올려\s*(주세요|놓으세요)|까지\s*(내|해)"
)


@dataclass
class Batch:
    """아직 필기로 만들지 않은 받아쓰기 묶음"""
    estimate: Estimate
    start_ms: int
    texts: list[str]
    since: float
    # 이 묶음을 위해 띄운 즉시 필기(임시 포스트잇)들
    previews: list[dict] = field(default_factory=list)


class LiveSession:
    def __init__(self, db: Database, llm: LLM, session: dict, send: Send):
        self.db = db
        self.llm = llm
        self.session_id = session["id"]
        self.document_id = session["document_id"]
        self.send = send

        self.pages = db.list_pages(self.document_id)
        self.tracker = PageTracker(PageIndex([p["text"] for p in self.pages]))
        self.vocab = vocabulary([p["text"] for p in self.pages])
        self.estimate: Estimate | None = None
        self.batch: Batch | None = None

        # 필기 호출은 한 번에 하나씩 (앞 필기를 "이미 쓴 필기"로 넘기기 위해).
        # 앞 호출이 도는 동안 생긴 묶음은 대기열에 두고, 같은 페이지끼리는 합쳐서 호출 수를 줄인다 (느린 무료 모델 대비).
        self._queue: list[Batch] = []
        self._worker: asyncio.Task | None = None
        self._preview_count = 0
        self.audio: LiveAudio | None = None

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

    def feed_audio(self, data: bytes, transcriber, wav_path: str | None) -> None:
        """웹앱이 보낸 마이크 소리. 처음 받을 때 실시간 Whisper 받아쓰기를 시작한다."""
        if self.audio is None:
            doc = self.db.get_document(self.document_id)
            self.audio = LiveAudio(transcriber, " ".join(doc["keywords"][:40]), self._on_heard, wav_path)
        self.audio.feed(data)

    async def _on_heard(self, text: str, start_ms: int, end_ms: int) -> None:
        await self.send({"type": "heard", "text": text})
        await self._on_transcript({"text": text, "start_ms": start_ms, "end_ms": end_ms})

    async def tick(self) -> None:
        """주기적으로 불려서, 오래 기다린 받아쓰기가 있으면 필기를 만든다."""
        if self.batch and time.monotonic() - self.batch.since >= settings.max_wait_seconds:
            self._schedule_flush()

    async def close(self) -> None:
        if self.audio:
            await self.audio.close()
        self._schedule_flush()
        if self._worker:
            await asyncio.gather(self._worker, return_exceptions=True)

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
        text = fix_terms(text, self.vocab)
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
        self._send_preview(batch)
        last = self._queue[-1] if self._queue else None
        if last and last.estimate.page_no == batch.estimate.page_no:
            last.texts.extend(batch.texts)
            last.estimate = batch.estimate
            last.previews.extend(batch.previews)
        else:
            self._queue.append(batch)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._drain())

    async def _drain(self) -> None:
        while self._queue:
            batch = self._queue.pop(0)
            ok = await self._annotate(batch)
            await self._resolve_previews(batch, keep=not ok)

    def _send_preview(self, batch: Batch) -> None:
        """AI를 기다리지 않고 바로 임시 포스트잇을 띄운다."""
        page = self.pages[batch.estimate.page_no - 1]
        note = quick_note(self.db.get_blocks(page["id"]), batch.texts)
        self._preview_count += 1
        preview = {"id": f"p{self._preview_count}", "page_no": batch.estimate.page_no, "page_id": page["id"],
                   "start_ms": batch.start_ms, **note}
        batch.previews.append(preview)
        payload = {k: v for k, v in preview.items() if k != "page_id"}
        task = asyncio.ensure_future(self.send({"type": "annotation_preview", "preview": payload}))
        task.add_done_callback(lambda t: t.cancelled() or t.exception())

    async def _resolve_previews(self, batch: Batch, keep: bool) -> None:
        """AI 필기가 나오면 임시 포스트잇을 지운다. AI가 실패했으면 임시 필기를 진짜 필기로 남긴다."""
        if not batch.previews:
            return
        if keep:
            for p in batch.previews:
                annotation = self.db.add_annotation(self.session_id, p["page_id"], p["block_id"], p["type"],
                                                    p["text"], p["start_ms"])
                await self.send({"type": "annotation_added", "annotation": annotation})
        await self.send({"type": "previews_resolved", "ids": [p["id"] for p in batch.previews]})

    async def _annotate(self, batch: Batch) -> bool:
        """AI로 필기·과제를 만든다. AI 호출이 실패하면 False."""
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
            existing_tasks = self.db.list_tasks(self.session_id)
            results = await self.llm.annotate(candidates, transcript, existing_tasks)
        except anthropic.RateLimitError:
            log.warning("필기 생성: 요청 한도 초과")
            await self.send({"type": "error", "message": "요청이 많아 잠시 AI 정리를 건너뜁니다."})
            return False
        except (anthropic.APIStatusError, anthropic.APIConnectionError, LLMError, json.JSONDecodeError) as exc:
            log.exception("필기 생성 실패")
            await self.send({"type": "error", "message": f"AI 정리 실패, 즉시 필기로 남겨 둡니다: {exc}"})
            return False

        by_page = {c["page_no"]: c for c in candidates}
        for item in results.get("tasks", []) if DIRECTIVE.search(transcript) else []:
            title = str(item.get("title", "")).strip()
            if not title or item.get("kind") not in TASK_KINDS:
                continue
            page = by_page.get(batch.estimate.page_no) or candidates[0]
            task = self.db.add_task(self.session_id, page["page_id"], item["kind"], title,
                                    str(item.get("instructions", "")).strip(), str(item.get("due_text", "")).strip())
            await self.send({"type": "task_added", "task": task})

        for item in results.get("annotations", []):
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
                note_type(item["type"], text),
                text,
                batch.start_ms,
                pending=pending,
            )
            await self.send({"type": "annotation_added", "annotation": annotation})
        return True
