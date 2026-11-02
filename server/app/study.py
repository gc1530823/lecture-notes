"""공부 도구: 강의가 끝난 뒤 플래시카드·개념 메모·마인드맵·암기(빈칸)·AI 튜터에 쓸 재료를 만든다.

- 암기(빈칸)는 AI 없이 규칙으로 만든다: 필기·정리 문장에서 강의자료 용어를 하나 골라 빈칸으로 바꾼다.
- 마인드맵은 AI가 실패하면 쪽 제목과 필기로 규칙대로 만든다.
- AI 튜터는 질문과 가장 가까운 쪽 3개(슬라이드 + 교수님 설명 + 필기)만 골라 넘긴다 (작은 모델도 문맥이 넘치지 않게).
"""

import math
import re

from .alignment import _grams
from .text_fix import VERB_ENDING

TERM = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}|[가-힣]{2,}")
PARTICLES = re.compile(r"(은|는|이|가|을|를|의|에|에서|으로|로|과|와|도|만|이란|란)$")


def _cosine(a: dict, b: dict) -> float:
    dot = sum(n * b.get(g, 0) for g, n in a.items())
    na = math.sqrt(sum(v * v for v in a.values())) or 1.0
    nb = math.sqrt(sum(v * v for v in b.values())) or 1.0
    return dot / (na * nb)


def page_material(pages: list[dict], segments: list[dict], annotations: list[dict]) -> list[dict]:
    """쪽마다 {page_no, title, slide, speech, notes}. 받아쓰기가 있는 쪽만."""
    result = []
    for page in pages:
        no = page["page_no"]
        speech = " ".join(s["text"] for s in segments if s["page_no"] == no)
        notes = [a for a in annotations if a["page_no"] == no and not a["pending"]]
        if not speech and not notes:
            continue
        title = (page.get("text") or "").strip().split("\n")[0][:40]
        result.append({"page_no": no, "title": title, "slide": page.get("text") or "", "speech": speech, "notes": notes})
    return result


def terms_of(text: str) -> list[str]:
    """강의자료(또는 노트 제목)에서 빈칸으로 낼 만한 용어: 동사 꼴이 아니고 두 글자 이상."""
    found = []
    for word in TERM.findall(text):
        word = PARTICLES.sub("", word) if "가" <= word[0] <= "힣" else word
        if len(word) >= 2 and not VERB_ENDING.search(word) and word not in found:
            found.append(word)
    return found


def cloze_items(material: list[dict], vocabulary: list[str], limit: int = 30) -> list[dict]:
    """필기 문장에서 용어 하나를 ____로 가린 암기 문제. 시험·강조 필기를 먼저."""
    order = {"exam": 0, "emphasis": 1, "explanation": 2, "example": 3}
    sentences = []
    for page in material:
        for note in sorted(page["notes"], key=lambda a: order.get(a["type"], 9)):
            for sentence in re.split(r"(?<=[.?!])\s+|\n", note["text"]):
                if len(sentence) >= 8:
                    sentences.append((order.get(note["type"], 9), page["page_no"], sentence.strip(), note["type"]))
    vocab = sorted(set(vocabulary), key=len, reverse=True)
    items, seen = [], set()
    for _, page_no, sentence, type_ in sorted(sentences, key=lambda s: s[0]):
        term = next((t for t in vocab if t in sentence and len(t) >= 2), None)
        if not term or sentence in seen:
            continue
        seen.add(sentence)
        items.append({"page_no": page_no, "text": sentence.replace(term, "____", 1), "answer": term,
                      "important": type_ in ("exam", "emphasis")})
        if len(items) >= limit:
            break
    return items


def fallback_mindmap(title: str, material: list[dict]) -> dict:
    """AI 없이: 가운데 = 강의 제목, 가지 = 쪽(제목), 잎 = 그 쪽의 필기 (짧게)."""
    def short(text: str) -> str:
        text = re.split(r"[.,:\n]", text)[0].strip()
        return text[:24] + ("…" if len(text) > 24 else "")

    return {"label": title, "children": [
        {"label": short(p["title"]) or f"{p['page_no']}쪽", "page_no": p["page_no"],
         "children": [{"label": short(n["text"])} for n in p["notes"][:4]]}
        for p in material
    ]}


def tutor_context(material: list[dict], question: str, overview: str = "", limit: int = 3) -> tuple[str, list[int]]:
    """질문과 가까운 쪽 몇 개를 골라 튜터에게 넘길 문맥을 만든다."""
    query = _grams(question)
    ranked = sorted(material, key=lambda p: -_cosine(query, _grams(f"{p['slide']} {p['speech']}")))
    chosen = sorted(ranked[:limit], key=lambda p: p["page_no"])
    parts = [f"<overview>\n{overview}\n</overview>"] if overview else []
    for p in chosen:
        notes = "\n".join(f"- ({n['type']}) {n['text']}" for n in p["notes"]) or "(없음)"
        parts.append(f'<page no="{p["page_no"]}">\n<slide>\n{p["slide"] or "(없음)"}\n</slide>\n'
                     f"<speech>\n{p['speech'][:3000]}\n</speech>\n<notes>\n{notes}\n</notes>\n</page>")
    return "\n\n".join(parts), [p["page_no"] for p in chosen]
