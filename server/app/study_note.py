"""AI 정리 노트 PDF: AI가 강의자료·교수님 설명·필기·시험 표시를 공부한 뒤, 교과서처럼 정리한 노트를 새로 쓴다.

필기가 붙은 슬라이드 PDF(notes_pdf.py)와 달리 슬라이드를 옮기지 않고 '배운 내용'을 주제별로 다시 정리한다.
  · 한눈에 보기 → 주제마다 핵심·설명·예시·시험 포인트 → 핵심 용어 → 시험에 나올 것 → 스스로 확인 문제(답은 맨 뒤)
한글은 함께 넣어 둔 나눔고딕(OFL)으로 PDF에 심는다.
"""

import html
import io
import os
from datetime import datetime

import pymupdf

FONTS = os.path.join(os.path.dirname(__file__), "fonts")
A4 = pymupdf.paper_rect("a4")
MARGIN = 46

STUDY_NOTE_SYSTEM = """당신은 이 과목을 아주 잘 정리하는 조교입니다. <material>의 강의자료(쪽마다 슬라이드 글), 교수님 설명(요약·받아쓰기),
필기, 교수님이 시험에 나온다고 한 것을 먼저 꼼꼼히 공부한 뒤, 학생이 시험 전에 이것 하나만 보면 되는 '정리 노트'를 새로 씁니다.

원칙:
- 슬라이드 문장을 그대로 옮기지 말고, 이해한 내용을 주제별로 다시 정리합니다. 교수님이 말로만 한 설명·예시도 넣습니다.
- sections: 강의 흐름대로 3~8개 주제. heading 은 짧은 제목, pages 는 근거가 된 쪽 번호들.
  points: 꼭 알아야 할 핵심 2~5개 (한 줄씩), explain: 왜 그런지·어떻게 동작하는지 2~4문장,
  example: 교수님 예시나 이해를 돕는 예 1~2문장 (없으면 빈 문자열), exam: 이 주제에서 시험에 나올 만한 것 1문장 (없으면 빈 문자열).
- terms: 핵심 용어 4~12개와 한 줄 뜻.
- exam_focus: 교수님이 시험에 나온다고 하거나 강조한 것 위주로 3~8개.
- check: 스스로 확인할 문제 4~8개와 짧은 답 (외운 문장 찾기가 아니라 이해를 묻는 문제).
- 강의에 없는 사실을 지어내지 않습니다. 한국어로, 짧고 또렷하게 씁니다."""

STUDY_NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "one_line": {"type": "string"},
        "sections": {"type": "array", "items": {
            "type": "object",
            "properties": {"heading": {"type": "string"}, "pages": {"type": "array", "items": {"type": "integer"}},
                           "points": {"type": "array", "items": {"type": "string"}}, "explain": {"type": "string"},
                           "example": {"type": "string"}, "exam": {"type": "string"}},
            "required": ["heading", "pages", "points", "explain", "example", "exam"], "additionalProperties": False}},
        "terms": {"type": "array", "items": {"type": "object", "properties": {"term": {"type": "string"}, "meaning": {"type": "string"}},
                                              "required": ["term", "meaning"], "additionalProperties": False}},
        "exam_focus": {"type": "array", "items": {"type": "string"}},
        "check": {"type": "array", "items": {"type": "object", "properties": {"q": {"type": "string"}, "a": {"type": "string"}},
                                              "required": ["q", "a"], "additionalProperties": False}},
    },
    "required": ["title", "one_line", "sections", "terms", "exam_focus", "check"],
    "additionalProperties": False,
}


def study_prompt(material_text: str, title: str, terms: list[dict]) -> str:
    glossary = "\n".join(f"- {t['term']}: {t.get('definition', '')}" for t in terms[:30])
    return f"<lecture_title>{title}</lecture_title>\n<material>\n{material_text}\n</material>\n<glossary>\n{glossary}\n</glossary>"


def clean_note(note: dict, title: str) -> dict:
    """빈 칸·이상한 모양을 걸러 낸다 (AI 가 일부를 빠뜨려도 PDF 는 만들어지게)"""
    def strs(xs):
        return [str(x).strip() for x in xs or [] if str(x).strip()]
    sections = []
    for s in note.get("sections") or []:
        if not str(s.get("heading", "")).strip():
            continue
        sections.append({"heading": str(s["heading"]).strip(), "pages": [p for p in s.get("pages") or [] if isinstance(p, int)],
                         "points": strs(s.get("points")), "explain": str(s.get("explain", "")).strip(),
                         "example": str(s.get("example", "")).strip(), "exam": str(s.get("exam", "")).strip()})
    return {
        "title": str(note.get("title") or title).strip() or title,
        "one_line": str(note.get("one_line", "")).strip(),
        "sections": sections,
        "terms": [{"term": str(t.get("term", "")).strip(), "meaning": str(t.get("meaning", "")).strip()}
                  for t in note.get("terms") or [] if str(t.get("term", "")).strip()],
        "exam_focus": strs(note.get("exam_focus")),
        "check": [{"q": str(c.get("q", "")).strip(), "a": str(c.get("a", "")).strip()}
                  for c in note.get("check") or [] if str(c.get("q", "")).strip()],
    }


CSS = """
@font-face { font-family: nanum; src: url(NanumGothic.ttf); }
@font-face { font-family: nanum; src: url(NanumGothicBold.ttf); font-weight: bold; }
body { font-family: nanum; font-size: 10.5pt; color: #1d1b2e; line-height: 1.55; }
.brand { font-size: 9pt; font-weight: bold; color: #6b5cf6; letter-spacing: 3pt; }
h1 { font-size: 24pt; margin: 6pt 0 4pt 0; }
.meta { color: #6f6d88; font-size: 9pt; }
.lead { background-color: #efecff; padding: 10pt 12pt; margin: 14pt 0 6pt 0; font-size: 11pt; }
.toc { margin: 6pt 0 0 0; color: #5d5b72; font-size: 9.5pt; }
h2 { font-size: 14.5pt; margin: 20pt 0 4pt 0; color: #4a3ad9; }
.pages { color: #9b99ad; font-size: 8.5pt; font-weight: normal; }
ul { margin: 4pt 0 4pt 0; padding-left: 14pt; }
li { margin: 0 0 2pt 0; }
.explain { margin: 6pt 0 0 0; }
.example { background-color: #eaf7ee; padding: 6pt 9pt; margin: 6pt 0 0 0; font-size: 9.8pt; }
.exam { background-color: #ffe9ee; padding: 6pt 9pt; margin: 6pt 0 0 0; font-size: 9.8pt; }
.label { font-weight: bold; font-size: 8.5pt; }
h3 { font-size: 12.5pt; margin: 22pt 0 6pt 0; color: #4a3ad9; }
table { width: 100%; border-collapse: collapse; }
td { padding: 4pt 6pt; border-bottom: 0.5pt solid #e2dff2; vertical-align: top; font-size: 9.8pt; }
td.term { font-weight: bold; width: 30%; }
.focus { background-color: #fff6e0; padding: 8pt 12pt; }
.q { margin: 8pt 0 0 0; font-weight: bold; }
.a { margin: 2pt 0 0 0; color: #3e3c55; }
"""


def _e(text: str) -> str:
    return html.escape(text or "")


def _html(note: dict, course_title: str, started_at: float | None) -> str:
    when = datetime.fromtimestamp(started_at).strftime("%Y년 %m월 %d일") if started_at else ""
    parts = ['<p class="brand">LUNE · AI 정리 노트</p>', f"<h1>{_e(note['title'])}</h1>",
             f'<p class="meta">{_e(course_title)}{" · " + when if when else ""}</p>']
    if note["one_line"]:
        parts.append(f'<div class="lead">{_e(note["one_line"])}</div>')
    if note["sections"]:
        parts.append('<p class="toc">' + " → ".join(_e(s["heading"]) for s in note["sections"]) + "</p>")
    for i, s in enumerate(note["sections"], 1):
        pages = f' <span class="pages">{", ".join(str(p) for p in s["pages"])}쪽</span>' if s["pages"] else ""
        parts.append(f"<h2>{i}. {_e(s['heading'])}{pages}</h2>")
        if s["points"]:
            parts.append("<ul>" + "".join(f"<li>{_e(p)}</li>" for p in s["points"]) + "</ul>")
        if s["explain"]:
            parts.append(f'<p class="explain">{_e(s["explain"])}</p>')
        if s["example"]:
            parts.append(f'<div class="example"><span class="label">예시 </span>{_e(s["example"])}</div>')
        if s["exam"]:
            parts.append(f'<div class="exam"><span class="label">시험 포인트 </span>{_e(s["exam"])}</div>')
    if note["terms"]:
        parts.append("<h3>핵심 용어</h3><table>" + "".join(
            f'<tr><td class="term">{_e(t["term"])}</td><td>{_e(t["meaning"])}</td></tr>' for t in note["terms"]) + "</table>")
    if note["exam_focus"]:
        parts.append('<h3>시험에 나올 것</h3><div class="focus"><ul>' + "".join(f"<li>{_e(x)}</li>" for x in note["exam_focus"])
                     + "</ul></div>")
    if note["check"]:
        parts.append("<h3>스스로 확인하기</h3>" + "".join(f'<p class="q">Q{i}. {_e(c["q"])}</p>'
                                                    for i, c in enumerate(note["check"], 1)))
        parts.append("<h3>확인 문제 답</h3>" + "".join(f'<p class="a"><b>A{i}.</b> {_e(c["a"])}</p>'
                                                  for i, c in enumerate(note["check"], 1)))
    return "".join(parts)


def build_study_pdf(note: dict, course_title: str, started_at: float | None = None) -> bytes:
    story = pymupdf.Story(html=_html(note, course_title, started_at), user_css=CSS, archive=pymupdf.Archive(FONTS))
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    where = A4 + (MARGIN, MARGIN + 6, -MARGIN, -MARGIN)
    more = True
    while more:
        dev = writer.begin_page(A4)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    doc = pymupdf.open("pdf", buf.getvalue())
    for i, page in enumerate(doc, 1):
        page.draw_rect(pymupdf.Rect(0, 0, A4.width, 8), color=None, fill=(0.29, 0.23, 0.85))
        page.insert_text((A4.width / 2 - 10, A4.height - 20), f"{i} / {len(doc)}", fontsize=8, color=(0.6, 0.6, 0.65))
    doc.subset_fonts()
    return doc.tobytes(garbage=3, deflate=True)
