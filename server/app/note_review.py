"""필기 두 번 쓰기: 수업이 끝난 뒤 강의 전체를 본 AI가 실시간 필기를 다시 확인해 바로잡는다.

실시간 필기는 "지금까지 들은 말"만 보고 몇 초 안에 써야 해서 쪽을 잘못 고르거나, 곧 이어질 설명을 몰라 틀리게 적기 쉽다.
끝난 뒤에는 그 필기 앞뒤 설명을 모두 볼 수 있으므로, 필기를 시간 순으로 몇 개씩 묶어 AI에게 보여 주고
  keep(그대로) · fix(내용 고침) · move(다른 쪽으로) · delete(틀렸거나 겹침)
를 고르게 하고, 놓친 시험·공지 언급이 있으면 더하게 한다.

안전장치: 사용자가 쓰거나 고친 필기·칠판 사진 필기는 건드리지 않는다. 한 묶음에서 절반 넘게 지우라고 하면 그 묶음의
지우기는 무시한다 (AI가 헛짚은 것으로 본다). 옮길 쪽은 보여 준 쪽 안에서만. 실패하면 실시간 필기를 그대로 둔다.
"""

import logging
import re

from .alignment import best_block
from .note_text import tidy

log = logging.getLogger(__name__)

CHUNK = 8                # 한 번에 확인할 필기 수
BEFORE_MS = 45_000       # 묶음의 첫 필기 앞 설명
AFTER_MS = 90_000        # 마지막 필기 뒤 설명 (무슨 말을 하려던 건지 알 수 있다)

REVIEW_SYSTEM = """당신은 대학 강의 필기를 검토하는 꼼꼼한 조교입니다. 수업 중에 급하게 붙인 필기를, 수업이 끝난 지금 다시 확인합니다.
<slides>에는 관련 슬라이드, <speech>에는 그 무렵 교수님이 실제로 한 말(앞에 [분:초]와 그때 추정한 쪽), <notes>에는 확인할 필기가 있습니다.
필기마다 하나를 고릅니다:
- keep: 교수님 말과 맞고 쪽도 맞음 (대부분 이것입니다. 확실하지 않으면 keep)
- fix: 교수님이 한 말과 다르게 적혔거나(숫자·용어·뜻이 틀림) 받아쓰기 오타가 그대로 들어감 → text에 바르게 고친 필기 (말투·길이는 원래대로 짧게)
- move: 내용은 맞는데 다른 슬라이드를 설명하던 것 → page_no에 맞는 쪽 (<slides>에 있는 쪽만)
- delete: 교수님이 그런 말을 하지 않았거나, 바로 앞 필기와 같은 내용이 겹침
교수님이 "시험에 나온다", "과제", "공지"라고 분명히 말했는데 필기가 없으면 missed에 더합니다 (type은 exam 또는 notice, at은 그 말의 [분:초], 최대 2개).
교수님이 하지 않은 말은 절대 지어내지 않습니다. 필기를 더 길게 풀어 쓰지 않습니다."""

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "notes": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "action": {"type": "string", "enum": ["keep", "fix", "move", "delete"]},
                           "text": {"type": "string"}, "page_no": {"type": "integer"}},
            "required": ["id", "action", "text", "page_no"], "additionalProperties": False}},
        "missed": {"type": "array", "items": {
            "type": "object",
            "properties": {"type": {"type": "string", "enum": ["exam", "notice"]}, "text": {"type": "string"},
                           "page_no": {"type": "integer"}, "at": {"type": "string"}},
            "required": ["type", "text", "page_no", "at"], "additionalProperties": False}},
    },
    "required": ["notes", "missed"],
    "additionalProperties": False,
}


def _clock(ms: int) -> str:
    return f"{ms // 60000}:{ms // 1000 % 60:02d}"


def reviewable(annotations: list[dict], photo_ids: set[int]) -> list[dict]:
    return [a for a in annotations if not a["edited_by_user"] and not a["pending"] and a["id"] not in photo_ids]


def build_prompt(notes: list[dict], segments: list[dict], pages: list[dict]) -> tuple[str, set[int]]:
    start, end = notes[0]["start_ms"] - BEFORE_MS, notes[-1]["start_ms"] + AFTER_MS
    speech = [s for s in segments if start <= s["start_ms"] <= end]
    numbers = {n["page_no"] for n in notes} | {s["page_no"] for s in speech if s["page_no"]}
    numbers |= {n + d for n in list(numbers) for d in (-1, 1)}
    shown = [p for p in pages if p["page_no"] in numbers][:8]
    slides = "\n".join(f'<slide page="{p["page_no"]}">\n{(p.get("text") or "")[:700]}\n</slide>' for p in shown)
    lines = "\n".join(f'[{_clock(s["start_ms"])}] ({s["page_no"] or "?"}쪽) {s["text"]}' for s in speech)
    listed = "\n".join(f'<note id="{n["id"]}" page="{n["page_no"]}" at="{_clock(n["start_ms"])}" type="{n["type"]}">{n["text"]}</note>'
                       for n in notes)
    return f"<slides>\n{slides}\n</slides>\n\n<speech>\n{lines}\n</speech>\n\n<notes>\n{listed}\n</notes>", {p["page_no"] for p in shown}


def _at_ms(text: str) -> int | None:
    m = re.match(r"\s*\[?(\d+):(\d{2})", text or "")
    return (int(m.group(1)) * 60 + int(m.group(2))) * 1000 if m else None


def apply(db, session_id: str, notes: list[dict], result: dict, allowed_pages: set[int], pages: list[dict]) -> dict:
    """AI의 판정을 안전장치를 거쳐 반영하고, 무엇을 얼마나 바꿨는지 돌려준다."""
    by_id = {n["id"]: n for n in notes}
    by_no = {p["page_no"]: p for p in pages}
    verdicts = [v for v in result.get("notes", []) if v.get("id") in by_id]
    deletes = [v for v in verdicts if v["action"] == "delete"]
    if len(deletes) > len(notes) / 2:
        log.warning("필기 다시 확인: 지우기가 너무 많아(%d/%d) 이 묶음의 지우기는 무시", len(deletes), len(notes))
        verdicts = [v for v in verdicts if v["action"] != "delete"]
    done = {"fixed": 0, "moved": 0, "deleted": 0, "added": 0}
    for v in verdicts:
        note = by_id[v["id"]]
        text = tidy(v.get("text") or "")
        if v["action"] == "fix" and text and text != note["text"] and len(text) <= max(200, 2 * len(note["text"])):
            db.review_annotation(note["id"], text=text)
            done["fixed"] += 1
        elif v["action"] == "move" and v.get("page_no") in allowed_pages and v["page_no"] != note["page_no"]:
            page = by_no[v["page_no"]]
            block = best_block(db.get_blocks(page["id"]), note["text"])
            db.review_annotation(note["id"], page_id=page["id"], block_id=block["id"] if block else None)
            done["moved"] += 1
        elif v["action"] == "delete":
            db.review_annotation(note["id"], delete=True)
            done["deleted"] += 1
        else:
            db.set_confidence(note["id"], max(note.get("confidence") or 0, 0.9))  # 다시 봐도 맞다
    existing = {n["text"] for n in notes}
    for m in result.get("missed", [])[:2]:
        text, at = tidy(m.get("text") or ""), _at_ms(m.get("at", ""))
        if text and at is not None and m.get("page_no") in allowed_pages and text not in existing:
            page = by_no[m["page_no"]]
            block = best_block(db.get_blocks(page["id"]), text)
            db.add_annotation(session_id, page["id"], block["id"] if block else None, m["type"], text[:200], at)
            done["added"] += 1
    return done


async def review_session(db, llm, session_id: str, pages: list[dict], photo_ids: set[int], on_progress=None) -> dict:
    review = getattr(llm, "review_notes", None)
    total = {"checked": 0, "fixed": 0, "moved": 0, "deleted": 0, "added": 0}
    if review is None:
        return total
    notes = sorted(reviewable(db.list_annotations(session_id), photo_ids), key=lambda a: a["start_ms"])
    segments = db.get_segments(session_id)
    chunks = [notes[i:i + CHUNK] for i in range(0, len(notes), CHUNK)]
    for i, chunk in enumerate(chunks):
        prompt, allowed = build_prompt(chunk, segments, pages)
        try:
            result = await review(prompt)
        except Exception:  # 한 묶음이 실패해도 나머지는 계속, 실시간 필기는 그대로 남는다
            log.exception("필기 다시 확인 실패 (묶음 %d/%d)", i + 1, len(chunks))
            continue
        done = apply(db, session_id, chunk, result or {}, allowed, pages)
        total["checked"] += len(chunk)
        for key, n in done.items():
            total[key] += n
        if on_progress:
            on_progress((i + 1) / len(chunks))
    return total
