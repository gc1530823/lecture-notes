"""교수님만 말한 내용: 받아쓰기·필기 가운데 슬라이드에 없는 설명을 찾는다.

문장의 글자 2-gram 가운데 그 페이지 슬라이드에도 있는 비율(포함도)이 낮으면 "슬라이드에 없는 설명"으로 본다.
AI 없이 바로 계산하고, 강의에 가야 하는 이유("오늘 설명의 42%는 슬라이드에 없었다")를 숫자로 보여 준다.
"""

from .alignment import _grams

BEYOND = 0.35  # 슬라이드와 겹치는 비율이 이보다 낮으면 슬라이드에 없는 설명
NOTE_TYPES = {"explanation", "example", "emphasis", "exam"}


def coverage(text: str, slide_text: str) -> float:
    grams = _grams(text)
    total = sum(grams.values())
    if not total:
        return 1.0
    slide = _grams(slide_text)
    return sum(n for g, n in grams.items() if g in slide) / total


def beyond_slides(page_texts: dict[int, str], segments: list[dict], annotations: list[dict]) -> dict:
    """{ratio: 슬라이드에 없는 설명의 글자 비율, annotation_ids: 교수님만 말한 필기, pages: 쪽별 비율}"""
    per_page: dict[int, list[int]] = {}
    for s in segments:
        if s["page_no"] is None:
            continue
        size = len(s["text"].replace(" ", ""))
        outside = coverage(s["text"], page_texts.get(s["page_no"], "")) < BEYOND
        bucket = per_page.setdefault(s["page_no"], [0, 0])
        bucket[0] += size if outside else 0
        bucket[1] += size
    total = sum(b[1] for b in per_page.values())
    ids = [a["id"] for a in annotations
           if not a["pending"] and a["type"] in NOTE_TYPES
           and coverage(a["text"], page_texts.get(a["page_no"], "")) < BEYOND]
    return {
        "ratio": round(sum(b[0] for b in per_page.values()) / total, 3) if total else 0.0,
        "annotation_ids": ids,
        "pages": [{"page_no": no, "ratio": round(b[0] / b[1], 3) if b[1] else 0.0} for no, b in sorted(per_page.items())],
    }
