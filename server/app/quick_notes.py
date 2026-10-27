"""즉시 필기: AI를 기다리지 않고 규칙만으로 바로 띄우는 임시 포스트잇.

무료 모드처럼 AI 응답이 수십 초 걸려도, 학생은 교수님 말을 듣는 그 순간 자료 위에서 핵심 문장을 본다.
AI 필기가 도착하면 앱은 임시 포스트잇을 지우고 AI 필기로 바꾼다.
"""

import re

from .alignment import best_block

# 위에 있을수록 우선한다: 시험·과제처럼 놓치면 안 되는 말을 먼저 잡는다
TYPE_RULES = [
    # "시험 문제를 외워서 푸는 것처럼" 같은 비유는 시험 공지가 아니므로, 시험에 나온다는 말이 있어야 한다
    ("exam", re.compile(r"(시험|퀴즈)\S*\s*(꼭\s*|반드시\s*)?(나와|나올|나옵|나간|낼|내요|냅니다)|출제|중간고사|기말고사")),
    ("notice", re.compile(r"과제|제출|레포트|리포트|마감|까지\s*(내|올려|제출)")),
    ("emphasis", re.compile(r"중요|꼭\s*기억|핵심|반드시|명심")),
    ("example", re.compile(r"예를\s*들|예시|비유|생각하면|비슷해요|처럼")),
]
FILLER_START = re.compile(r"^(자|음|어|그|그래서|근데|아)\s+")
MAX_CHARS = 70


def _sentences(texts: list[str]) -> list[str]:
    parts = []
    for text in texts:
        parts += [s.strip() for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]
    return parts


def _shorten(sentence: str) -> str:
    sentence = FILLER_START.sub("", sentence).strip()
    if len(sentence) <= MAX_CHARS:
        return sentence
    cut = sentence[:MAX_CHARS]
    return (cut[: cut.rfind(" ")] if " " in cut else cut) + "…"


def quick_note(blocks: list[dict], texts: list[str]) -> dict:
    """받아쓰기 묶음에서 핵심 문장 하나를 골라 종류와 붙일 문단을 정한다."""
    sentences = _sentences(texts) or texts
    for kind, pattern in TYPE_RULES:
        for sentence in sentences:
            if pattern.search(sentence):
                block = best_block(blocks, sentence)
                return {"type": kind, "text": _shorten(sentence), "block_id": block["id"] if block else None}
    # 규칙에 안 걸리면 자료와 가장 많이 겹치는 문장 (설명 중인 내용일 가능성이 크다)
    scored = [(best_block(blocks, s, threshold=0.0), s) for s in sentences]
    block, sentence = max(scored, key=lambda bs: (bs[0] is not None, len(bs[1])))
    return {"type": "explanation", "text": _shorten(sentence), "block_id": block["id"] if block else None}
