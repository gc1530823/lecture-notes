"""시험 공부 도구 (AI 없이 규칙으로):

- 망각 곡선 복습: 카드마다 다음 복습 날짜를 정한다 (Anki가 쓰는 SM-2를 단순하게).
  틀리면 10분 뒤 다시, 맞히면 1일 → 3일 → 점점 길게. 쉬웠다/어려웠다에 따라 늘어나는 비율(ease)을 조절한다.
- 족보 노트: 한 강의자료의 모든 강의에서 시험 필기·강조·유력한 쪽·용어·"모르겠다"·예상 문제를 모아 한 장으로.
  AI가 새로 쓰지 않고 이미 만든 것만 모으므로 빠르고, 없는 말을 지어내지 않는다.
"""

import hashlib
import re
import time

DAY = 86400.0
MIN_EASE = 1.3
NEW_PER_DAY = 20
GRADES = {"again": 0, "hard": 1, "good": 2, "easy": 3}


def card_key(source: str, front: str) -> str:
    return hashlib.sha1(f"{source}\0{' '.join(front.split())}".encode()).hexdigest()[:20]


def schedule(card: dict, grade: int, now: float | None = None) -> dict:
    """card: {ease, interval(일), reps, lapses}. grade: 0 다시 · 1 어려움 · 2 알맞음 · 3 쉬움 → 바뀐 카드"""
    now = time.time() if now is None else now
    ease, interval, reps, lapses = card["ease"], card["interval"], card["reps"], card["lapses"]
    if grade == 0:
        reps, lapses, interval = 0, lapses + 1, 0.0
        ease = max(MIN_EASE, ease - 0.2)
        due = now + 600  # 10분 뒤 다시
    else:
        if grade == 1:
            interval = max(1.0, interval * 1.2)
            ease = max(MIN_EASE, ease - 0.15)
        elif reps == 0:
            interval = 4.0 if grade == 3 else 1.0
        elif reps == 1:
            interval = 6.0 if grade == 3 else 3.0
        else:
            interval = interval * ease * (1.3 if grade == 3 else 1.0)
        if grade == 3:
            ease += 0.15
        reps += 1
        due = now + interval * DAY
    return {**card, "ease": round(ease, 3), "interval": round(interval, 3), "reps": reps, "lapses": lapses,
            "due_at": due, "last_at": now}


# 족보 노트

def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.lower())


def _dedupe(items: list[dict], key) -> list[dict]:
    seen, out = set(), []
    for item in items:
        k = _norm(key(item))[:60]
        if k and k not in seen:
            seen.add(k)
            out.append(item)
    return out


def build_jokbo(doc: dict, sessions: list[dict], scores: list[dict], top: list[int], questions: list[dict]) -> dict:
    """sessions: [{id, started_at, annotations, terms, marks, summary}]"""
    notes = [dict(a, lecture=i + 1) for i, s in enumerate(sessions) for a in s["annotations"] if not a["pending"]]
    by_page = {p["page_no"]: p for p in doc["pages"]}

    def title(no: int) -> str:
        text = (by_page.get(no, {}).get("text") or "").strip().split("\n")[0]
        return text[:40]

    summaries: dict[int, str] = {}
    for s in sessions:  # 최근 강의의 요약이 앞선다
        for p in ((s.get("summary") or {}).get("pages") or []):
            summaries.setdefault(p["page_no"], p["summary"])

    score_by_page = {s["page_no"]: s for s in scores}
    top_pages = [{"page_no": no, "title": title(no), "score": score_by_page[no]["score"],
                  "reasons": score_by_page[no]["reasons"], "summary": summaries.get(no, "")}
                 for no in top if no in score_by_page]

    def pick(kind: str) -> list[dict]:
        found = sorted((n for n in notes if n["type"] == kind), key=lambda n: (n["page_no"], n["start_ms"]))
        return [{"page_no": n["page_no"], "text": n["text"], "lecture": n["lecture"]} for n in _dedupe(found, lambda n: n["text"])]

    terms = _dedupe([dict(t, lecture=i + 1) for i, s in enumerate(sessions) for t in s["terms"]], lambda t: t["term"])
    confused = [dict(m, lecture=i + 1) for i, s in enumerate(sessions) for m in s["marks"]]
    predicted = [{"page_no": q["page_no"], **item} for q in questions for item in q["questions"]]

    return {
        "title": doc["title"],
        "lectures": len(sessions),
        "exam": pick("exam"),
        "emphasis": pick("emphasis"),
        "notice": pick("notice"),
        "top_pages": top_pages,
        "terms": [{"term": t["term"], "definition": t["definition"], "page_no": t["page_no"]} for t in terms],
        "confused": [{"page_no": m["page_no"], "speech": m["speech"], "explanation": m["explanation"], "lecture": m["lecture"]}
                     for m in confused],
        "predicted": predicted,
    }
