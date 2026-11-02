"""AI가 놓친 실수를 규칙으로 바로잡는다.

1. 받아쓰기 용어 교정: 받아쓰기는 낯선 전문용어의 첫 자음을 잘못 듣곤 한다 ("뉴런" → "유런", "검증" → "범증").
   강의자료에 있는 용어와 한 글자의 첫 자음만 다르면 그 용어로 고친다. 다른 경우는 건드리지 않는다.
2. 시험 표시: 필기에 "중간고사", "출제"처럼 시험에 나온다는 말이 있으면 종류를 '시험'으로 맞춘다.
"""

import re

from .pdf_parser import _strip_particle

HANGUL = re.compile(r"[가-힣]{2,}")
# "오르면"·"정한다" 같은 동사 꼴은 용어가 아니다 (있으면 "모르면"을 "오르면"으로 잘못 고친다)
VERB_ENDING = re.compile(r"(다|면|고|서|며|게|지|요|니|는|던|도록|어|아|해|하|된|한|할|인)$")
# 시험에 나온다는 필기 ("시험 문제를 외워서 푸는 학생" 같은 비유는 해당하지 않는다)
NOTE_EXAM = re.compile(r"중간고사|기말고사|출제|시험에\s*(꼭\s*|반드시\s*)?(나와|나올|나옵|나오|나간|냅)")


def _split(syllable: str) -> tuple[int, int]:
    """한글 한 글자 → (첫 자음, 나머지 모음·받침)."""
    code = ord(syllable) - 0xAC00
    return code // 588, code % 588


def vocabulary(page_texts: list[str]) -> set[str]:
    words = set()
    for text in page_texts:
        for word in HANGUL.findall(text):
            word = _strip_particle(word)
            if not VERB_ENDING.search(word):
                words.add(word)
    return words


def _correction(run: str, vocab: set[str]) -> str | None:
    """run(띄어쓰기 단위의 한글)의 앞부분이 자료 용어와 첫 자음 하나만 다르면 고친 run을 돌려준다."""
    found = None
    for n in range(len(run), 1, -1):
        stem = run[:n]
        if stem in vocab:
            return None  # 이미 자료에 있는 말
        for term in vocab:
            if len(term) != n:
                continue
            diffs = [i for i in range(n) if stem[i] != term[i]]
            if len(diffs) != 1:
                continue
            i = diffs[0]
            same_rest = _split(stem[i])[1] == _split(term[i])[1]
            # 끝 글자만 다른 경우("기울지" ↔ "기울기")는 말끝일 수 있어 뒤에 조사가 붙었을 때만 고친다
            if same_rest and (i < n - 1 or len(run) > n):
                if found and found != term:
                    return None  # 후보가 둘 이상이면 고치지 않는다
                found = term
        if found:
            return found + run[n:]
    return None


def fix_terms(text: str, vocab: set[str]) -> str:
    if not vocab:
        return text

    def replace(match: re.Match) -> str:
        return _correction(match.group(0), vocab) or match.group(0)

    return HANGUL.sub(replace, text)


def note_type(type_: str, text: str) -> str:
    if type_ in ("explanation", "emphasis", "example") and NOTE_EXAM.search(text):
        return "exam"
    return type_
