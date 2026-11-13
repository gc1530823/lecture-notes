"""강의 스토리와 수업 흐름, 연속 공부: 이미 있는 필기·받아쓰기·표시로 규칙만으로 만든다 (AI를 부르지 않아 한도가 없다).

- 스토리: 강의 하나를 1분 안에 넘겨 보는 카드 묶음 (표지 → 시험에 나온다고 한 것 → 강조 → 목소리를 높인 순간 →
  모르겠다고 표시한 곳 → 과제 → 새 용어 → 마무리). 카드마다 그 순간의 녹음 시각이 있어 눌러서 들을 수 있다.
- 흐름: 강의를 1분씩 잘라 말의 양·필기·시험 언급·모르겠다·목소리 높임을 센다 (어디가 중요한 구간이었는지 한눈에).
- 연속 공부: 강의를 듣거나 복습한 날을 세어 며칠째 이어 가는지.
"""

import datetime

MINUTE = 60_000


def _quote(segments: list[dict], at_ms: int) -> str:
    """그 필기 무렵 교수님이 실제로 한 말 한 문장"""
    near = [s for s in segments if abs(s["start_ms"] - at_ms) <= 20_000]
    if not near:
        return ""
    best = min(near, key=lambda s: abs(s["start_ms"] - at_ms))
    return best["text"][:140]


def build_story(title: str, started_at: float, annotations: list[dict], segments: list[dict], marks: list[dict],
                tasks: list[dict], terms: list[dict], summary: dict | None) -> dict:
    notes = [a for a in annotations if not a.get("pending")]
    duration = max([s["end_ms"] for s in segments] + [a["start_ms"] for a in notes] + [0])
    cards: list[dict] = []

    def add(kind: str, label: str, text: str, page_no=None, at_ms=None, quote: str = "", tone: str = "explanation") -> None:
        if text and not any(c["text"] == text for c in cards):
            cards.append({"kind": kind, "label": label, "text": text[:220], "page_no": page_no, "at_ms": at_ms,
                          "quote": quote if quote and quote != text else "", "tone": tone})

    overview = (summary or {}).get("overview") or ""
    add("cover", "오늘 강의", overview or title, tone="notice")
    for a in [a for a in notes if a["type"] == "exam"][:3]:
        add("exam", "시험에 나온대요", a["text"], a["page_no"], a["start_ms"], _quote(segments, a["start_ms"]), "exam")
    for a in [a for a in notes if a["type"] == "emphasis"][:2]:
        add("emphasis", "교수님이 강조했어요", a["text"], a["page_no"], a["start_ms"], _quote(segments, a["start_ms"]), "emphasis")
    for s in [s for s in segments if s.get("loud")][:1]:
        add("loud", "목소리를 높인 순간", s["text"], s.get("page_no"), s["start_ms"], tone="qa")
    for m in marks[:1]:
        add("confused", "여기서 막혔어요", m.get("explanation") or m.get("speech") or "나중에 다시 볼 곳으로 표시했어요",
            m["page_no"], m["at_ms"], m.get("speech", "") if m.get("explanation") else "", "tip")
    for t in tasks[:1]:
        due = f" ({t['due_text']})" if t.get("due_text") else ""
        add("task", "잊지 마세요", f"{t['title']}{due}", t.get("page_no"), tone="notice")
    for term in terms[:2]:
        add("term", "새로 나온 말", f"{term['term']}: {term['definition']}", term.get("page_no"), term.get("start_ms"), tone="example")
    if len(cards) <= 2:  # 눈에 띄는 필기가 없던 강의: 아무 필기나 몇 개
        for a in notes[:3]:
            add("note", "필기", a["text"], a["page_no"], a["start_ms"], _quote(segments, a["start_ms"]), "explanation")
    stats = {"minutes": round(duration / MINUTE), "notes": len(notes), "exam": sum(a["type"] == "exam" for a in notes),
             "terms": len(terms), "confused": len(marks), "pages": len({a["page_no"] for a in notes})}
    cards.append({"kind": "end", "label": "오늘 수업 끝", "text": "", "page_no": None, "at_ms": None, "quote": "", "tone": "notice"})
    return {"title": title, "started_at": started_at, "cards": cards, "stats": stats, "flow": build_flow(notes, segments, marks, duration)}


def build_flow(notes: list[dict], segments: list[dict], marks: list[dict], duration_ms: int) -> dict:
    count = max(1, -(-duration_ms // MINUTE))
    minutes = [{"minute": i, "speech": 0, "notes": 0, "exam": 0, "confused": 0, "loud": 0, "page": None} for i in range(count)]

    def at(ms: int) -> dict:
        return minutes[min(count - 1, max(0, ms // MINUTE))]

    for s in segments:
        m = at(s["start_ms"])
        m["speech"] += len(s["text"])
        m["loud"] += 1 if s.get("loud") else 0
        m["page"] = s.get("page_no") or m["page"]
    for a in notes:
        m = at(a["start_ms"])
        m["notes"] += 1
        m["exam"] += 1 if a["type"] == "exam" else 0
    for mark in marks:
        at(mark["at_ms"])["confused"] += 1
    peak = max((m["speech"] for m in minutes), default=0) or 1
    for m in minutes:
        # 중요도: 시험 언급 > 모르겠다 > 목소리 높임 > 필기 > 말의 양
        m["weight"] = round(min(1.0, 0.25 * m["speech"] / peak + 0.35 * min(m["exam"], 2) / 2 + 0.15 * min(m["notes"], 3) / 3
                                + 0.15 * min(m["confused"], 1) + 0.10 * min(m["loud"], 1)), 3)
    return {"duration_ms": duration_ms, "minutes": minutes}


def build_streak(stamps: list[float], tz_minutes: int, now: float) -> dict:
    """stamps: 강의를 시작했거나 복습한 시각들. tz_minutes: 사용자 시간대(한국 540). 오늘 또는 어제까지 이어진 날 수."""
    tz = datetime.timezone(datetime.timedelta(minutes=tz_minutes))
    days = {datetime.datetime.fromtimestamp(s, tz).date() for s in stamps if s}
    today = datetime.datetime.fromtimestamp(now, tz).date()
    day = today if today in days else today - datetime.timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= datetime.timedelta(days=1)
    best = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev and (d - prev).days == 1 else 1
        best = max(best, run)
        prev = d
    week = [{"date": (today - datetime.timedelta(days=i)).isoformat(), "done": (today - datetime.timedelta(days=i)) in days}
            for i in range(6, -1, -1)]
    return {"streak": streak, "best": best, "today": today in days, "week": week, "days": len(days), **level(len(days))}


# 레벨: 공부한 날마다 불꽃 하나, 불꽃이 모이면 레벨이 오른다
LEVELS = [(0, "첫걸음"), (3, "새내기"), (7, "모범생"), (14, "우등생"), (30, "장학생"), (60, "수석"), (100, "전설")]


def level(carrots: int) -> dict:
    index = max(i for i, (need, _) in enumerate(LEVELS) if carrots >= need)
    nxt = LEVELS[index + 1][0] if index + 1 < len(LEVELS) else None
    return {"carrots": carrots, "level": index + 1, "level_name": LEVELS[index][1], "level_from": LEVELS[index][0], "next_at": nxt}


def build_exam_story(title: str, sessions: list[dict]) -> dict:
    """시험 전날 스토리: 그 강의자료의 모든 강의에서 시험에 나온다고 한 것 · 강조 · 막혔던 곳만 모아 넘겨 본다.
    sessions: [{id, started_at, annotations, segments, marks}] (오래된 강의부터)"""
    cards: list[dict] = []

    def add(kind, label, text, tone, session=None, page_no=None, at_ms=None, quote=""):
        if text and not any(c["text"] == text for c in cards):
            cards.append({"kind": kind, "label": label, "text": text[:220], "page_no": page_no, "at_ms": at_ms, "quote": quote if quote != text else "",
                          "tone": tone, "session_id": session})

    exam = [(i, s, a) for i, s in enumerate(sessions) for a in s["annotations"] if not a["pending"] and a["type"] == "exam"]
    emphasis = [(i, s, a) for i, s in enumerate(sessions) for a in s["annotations"] if not a["pending"] and a["type"] == "emphasis"]
    marks = [(i, s, m) for i, s in enumerate(sessions) for m in s["marks"]]
    add("cover", "시험 전날 총정리", f"교수님이 시험에 나온다고 한 것 {len(exam)}개, 강조한 것 {len(emphasis)}개를 모았어요", "notice")
    for i, s, a in exam[:12]:
        add("exam", f"{i + 1}번째 강의 · 시험에 나온대요", a["text"], "exam", s["id"], a["page_no"], a["start_ms"], _quote(s["segments"], a["start_ms"]))
    for i, s, a in emphasis[:4]:
        add("emphasis", f"{i + 1}번째 강의 · 강조", a["text"], "emphasis", s["id"], a["page_no"], a["start_ms"], _quote(s["segments"], a["start_ms"]))
    for i, s, m in marks[:3]:
        add("confused", "여기서 막혔었어요", m.get("explanation") or m.get("speech") or "다시 볼 곳으로 표시했던 쪽이에요", "tip", s["id"], m["page_no"], m["at_ms"])
    notes = sum(1 for s in sessions for a in s["annotations"] if not a["pending"])
    minutes = sum(max([x["end_ms"] for x in s["segments"]] + [0]) for s in sessions) // MINUTE
    cards.append({"kind": "end", "label": "준비 끝", "text": "", "page_no": None, "at_ms": None, "quote": "", "tone": "notice", "session_id": None})
    return {"title": title, "started_at": sessions[-1]["started_at"] if sessions else 0, "cards": cards,
            "stats": {"minutes": minutes, "notes": notes, "exam": len(exam), "terms": len(marks), "confused": len(marks), "pages": 0},
            "flow": {"duration_ms": 0, "minutes": []}}



def wave(notes: list[dict], segments: list[dict], marks: list[dict], buckets: int = 28) -> dict:
    """강의의 소리 무늬: 수업 흐름(1분 단위 중요도)을 같은 수의 막대로 줄인 것. 강의마다 다른 모양이 된다.
    w: 막대 높이 0~9 를 이어 쓴 글자, x: 시험 언급이 있던 막대 번호"""
    duration = max([s["end_ms"] for s in segments] + [a["start_ms"] for a in notes] + [0])
    if duration == 0:
        return {"w": "", "x": []}
    minutes = build_flow(notes, segments, marks, duration)["minutes"]
    heights, exams = [], []
    for i in range(buckets):
        part = minutes[i * len(minutes) // buckets: max(i * len(minutes) // buckets + 1, (i + 1) * len(minutes) // buckets)]
        heights.append(max(m["weight"] for m in part))
        if any(m["exam"] for m in part):
            exams.append(i)
    top = max(heights) or 1
    return {"w": "".join(str(min(9, round(9 * h / top))) for h in heights), "x": exams}
