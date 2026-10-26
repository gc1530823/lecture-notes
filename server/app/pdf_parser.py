"""강의자료 PDF를 페이지와 텍스트 블록(정규화 좌표)으로 나눈다."""

import re
from collections import Counter

import pymupdf

# 블록 좌표는 페이지 크기로 나눈 0~1 값이고, 원점은 왼쪽 위다.
# iPhone 앱은 이 값에 화면에 그린 페이지 크기를 곱해서 위치를 잡는다.

MIN_BLOCK_CHARS = 2
IMAGE_BLOCK_TEXT = "[그림]"

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "are", "from", "then", "else",
    "그리고", "그러나", "하지만", "또는", "있다", "없다", "한다", "된다", "이다", "대한", "통해", "위해",
}


class PDFParseError(ValueError):
    pass


def parse_pdf(data: bytes) -> list[dict]:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF가 여러 종류의 예외를 던진다
        raise PDFParseError("PDF 파일을 열 수 없습니다.") from exc

    pages = []
    with doc:
        for index, page in enumerate(doc):
            rect = page.rect
            blocks = []
            for x0, y0, x1, y1, text, _no, kind in page.get_text("blocks", sort=True):
                text = " ".join(text.split())
                if kind == 1:
                    text = IMAGE_BLOCK_TEXT
                elif len(text) < MIN_BLOCK_CHARS:
                    continue
                blocks.append({
                    "x": max(0.0, x0 / rect.width),
                    "y": max(0.0, y0 / rect.height),
                    "w": min(1.0, (x1 - x0) / rect.width),
                    "h": min(1.0, (y1 - y0) / rect.height),
                    "text": text,
                })
            pages.append({
                "page_no": index + 1,
                "width": rect.width,
                "height": rect.height,
                "text": "\n".join(b["text"] for b in blocks if b["text"] != IMAGE_BLOCK_TEXT),
                "blocks": blocks,
            })
    if not pages:
        raise PDFParseError("페이지가 없는 PDF입니다.")
    return pages


# 한국어 단어 끝의 조사를 떼어 용어만 남긴다 ("방향으로" → "방향")
PARTICLES = ("으로", "에서", "에게", "까지", "부터", "보다", "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도")


def _strip_particle(word: str) -> str:
    for particle in PARTICLES:
        if word.endswith(particle) and len(word) - len(particle) >= 2:
            return word[: -len(particle)]
    return word


def extract_keywords(pages: list[dict], limit: int = 100) -> list[str]:
    """자주 나오는 용어를 뽑는다. iPhone 음성 인식에 힌트(contextualStrings)로 넘긴다."""
    counts: Counter[str] = Counter()
    for page in pages:
        for word in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}|[가-힣]{2,}", page["text"]):
            word = _strip_particle(word) if "가" <= word[0] <= "힣" else word
            if word.lower() not in STOPWORDS:
                counts[word] += 1
    return [word for word, _ in counts.most_common(limit)]
