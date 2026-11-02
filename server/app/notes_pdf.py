"""강의 정리 PDF: 페이지마다 필기가 붙은 슬라이드 + 포스트잇 + 정리 노트 + 교수님 설명, 끝에 과제.

슬라이드는 원본 PDF 위에 형광펜과 번호 깃발을 그린 뒤 그림으로 넣고, 글은 PyMuPDF Story(HTML)로 흘려 쓴다.
한글은 함께 넣어 둔 나눔고딕(OFL)으로 PDF에 심는다.
"""

import html
import io
import os
from datetime import datetime

import pymupdf

FONTS = os.path.join(os.path.dirname(__file__), "fonts")
A4 = pymupdf.paper_rect("a4")
MARGIN = 40

TYPES = {
    "explanation": ("보충설명", (1.00, 0.93, 0.58), (0.85, 0.62, 0.00)),
    "example": ("예시", (0.76, 0.94, 0.80), (0.13, 0.62, 0.33)),
    "emphasis": ("강조", (1.00, 0.84, 0.66), (0.93, 0.45, 0.07)),
    "exam": ("시험", (1.00, 0.75, 0.80), (0.88, 0.18, 0.33)),
    "notice": ("공지", (0.85, 0.82, 1.00), (0.42, 0.33, 0.90)),
    "tip": ("AI 팁", (0.78, 0.92, 1.00), (0.05, 0.52, 0.80)),
    "qa": ("질문", (0.98, 0.85, 0.96), (0.75, 0.22, 0.62)),
}
TASK_KINDS = {"in_class": "수업 중 과제", "homework": "숙제", "report": "레포트", "exam_prep": "시험 준비"}

CSS = """
@font-face { font-family: nanum; src: url(NanumGothic.ttf); }
@font-face { font-family: nanum; src: url(NanumGothicBold.ttf); font-weight: bold; }
body { font-family: nanum; font-size: 10pt; color: #211f1c; line-height: 1.45; }
h1 { font-size: 22pt; margin: 0 0 4pt 0; }
h2 { font-size: 14pt; margin: 14pt 0 6pt 0; color: #3d36b8; }
h3 { font-size: 11pt; margin: 10pt 0 4pt 0; }
.muted { color: #6b6760; }
.small { font-size: 8.5pt; }
.note { padding: 5pt 7pt; margin: 0 0 5pt 0; }
.kind { font-weight: bold; font-size: 8.5pt; }
.overview { background-color: #ecebff; padding: 8pt 10pt; }
li { margin-bottom: 2pt; }
"""


def _rgb_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(c * 255):02x}" for c in rgb)


def _slide_image(src: pymupdf.Document, page_info: dict, notes: list[dict]) -> bytes:
    """원본 슬라이드 한 장에 형광펜(필기가 붙은 문단)과 번호 깃발을 그려 그림으로 만든다."""
    doc = pymupdf.open()
    doc.insert_pdf(src, from_page=page_info["page_no"] - 1, to_page=page_info["page_no"] - 1)
    page = doc[0]
    r = page.rect
    blocks = {b["id"]: b for b in page_info["blocks"]}
    for block_id in {n["block_id"] for n in notes if n["block_id"] in blocks}:
        b = blocks[block_id]
        last = [n for n in notes if n["block_id"] == block_id][-1]
        rect = pymupdf.Rect(b["x"] * r.width - 3, b["y"] * r.height, (b["x"] + b["w"]) * r.width + 3,
                            (b["y"] + b["h"]) * r.height)
        page.draw_rect(rect, color=None, fill=TYPES[last["type"]][2], fill_opacity=0.22, overlay=True)
    loose = 0
    size = max(r.width / 40, 10)
    for i, n in enumerate(notes, start=1):
        b = blocks.get(n["block_id"])
        if b:
            same = sum(1 for m in notes[: i - 1] if m["block_id"] == n["block_id"])
            x = min((b["x"] + b["w"]) * r.width + size * 0.6 + same * size * 1.4, r.width - size * 1.2)
            y = (b["y"] + b["h"] / 2) * r.height - size / 2
        else:
            x, y = size * 0.8 + loose * size * 1.4, r.height - size * 1.6
            loose += 1
        flag = pymupdf.Rect(x, y, x + size * 1.15, y + size)
        page.draw_rect(flag, color=TYPES[n["type"]][2], fill=TYPES[n["type"]][1], width=0.6, overlay=True)
        fs = size * 0.62
        label = str(i)
        tw = pymupdf.get_text_length(label, fontname="helv", fontsize=fs)
        page.insert_text((flag.x0 + (flag.width - tw) / 2, flag.y1 - (flag.height - fs * 0.72) / 2), label,
                         fontsize=fs, fontname="helv", color=(0.13, 0.12, 0.11), overlay=True)
    zoom = 1100 / max(r.width, 1)
    return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("jpg", jpg_quality=85)


def build_notes_pdf(pdf_path: str, title: str, pages: list[dict], annotations: list[dict], segments: list[dict],
                    tasks: list[dict], summary: dict | None, organized: dict | None, started_at: float,
                    beyond: dict | None = None) -> bytes:
    # 노트 모드(강의자료 없는 수업)는 슬라이드 그림 없이 주제 제목과 필기·정리만 넣는다
    src = pymupdf.open(pdf_path) if pdf_path and os.path.exists(pdf_path) else None
    beyond_ids = set((beyond or {}).get("annotation_ids", []))
    archive = pymupdf.Archive(FONTS)
    images: dict[str, bytes] = {}
    esc = html.escape
    points_by_page = {p["page_no"]: p.get("points", []) for p in (organized or {}).get("pages", [])}
    fixed_speech = {p["page_no"]: p["speech"] for p in (organized or {}).get("pages", []) if p.get("speech")}
    summary_by_page = {p["page_no"]: p["summary"] for p in (summary or {}).get("pages", [])}

    head = [f"<h1>{esc(title)}</h1>",
             f"<p class='muted'>{datetime.fromtimestamp(started_at):%Y년 %m월 %d일 %H:%M} 강의 · "
             f"필기 {sum(1 for a in annotations if not a['pending'])}개 · 과제 {len(tasks)}개</p>"]
    if beyond and beyond.get("ratio"):
        head.append(f"<p><b>오늘 교수님 설명의 {round(beyond['ratio'] * 100)}%는 슬라이드에 없던 내용</b>"
                    "<span class='muted'> · 필기에 [슬라이드에 없음] 표시</span></p>")
    if summary and summary.get("overview"):
        head.append(f"<div class='overview'><b>한눈에 보는 강의</b><br>{esc(summary['overview'])}</div>")

    sections: list[list[str]] = []
    for page in pages:
        no = page["page_no"]
        notes = [a for a in annotations if a["page_no"] == no and not a["pending"]]
        speech = [s for s in segments if s["page_no"] == no]
        points = points_by_page.get(no, [])
        if not (notes or speech or points):
            continue
        name = f"slide{no}.jpg"
        if src is None:
            parts = [f"<h2>{no}. {esc(page.get('text') or '')}</h2>"]
        else:
            images[name] = _slide_image(src, page, notes)
            # 세로로 긴 자료도 한 쪽 안에서 글과 함께 보이도록 그림 높이를 400pt 안으로 줄인다
            ratio = (page.get("height") or 1) / (page.get("width") or 1)
            width = round(min(515, 400 / ratio))
            parts = [f"<h2>{no}쪽</h2><img src='{name}' width='{width}'/>"]
        sections.append(parts)
        if notes:
            parts.append("<h3>필기</h3>")
            for i, n in enumerate(notes, start=1):
                label, paper, ink = TYPES.get(n["type"], TYPES["explanation"])
                parts.append(f"<div class='note' style='background-color:{_rgb_hex(paper)}'>"
                             f"<span class='kind' style='color:{_rgb_hex(ink)}'>{i}. {label}</span> {esc(n['text']).replace(chr(10), '<br>')}"
                             + (" <span class='kind' style='color:#5b4fe0'>[슬라이드에 없음]</span>" if n.get("id") in beyond_ids else "")
                             + "</div>")
        if points:
            parts.append("<h3>정리 노트</h3><ul>" + "".join(f"<li>{esc(p)}</li>" for p in points) + "</ul>")
        elif no in summary_by_page:
            parts.append(f"<h3>정리 노트</h3><p>{esc(summary_by_page[no])}</p>")
        if speech:
            # AI가 잘못 들린 단어만 고친 받아쓰기가 있으면 그것을 쓴다
            text = fixed_speech.get(no) or " ".join(s["text"] for s in speech)
            parts.append(f"<h3>교수님 설명 (받아쓰기)</h3><p class='small muted'>{esc(text)}</p>")

    parts = []
    pending = [a for a in annotations if a["pending"]]
    if pending:
        parts.append("<h2>페이지를 정하지 못한 필기</h2>"
                     + "".join(f"<div class='note' style='background-color:#f0ede8'>{esc(a['text'])}</div>" for a in pending))
    if tasks:
        parts.append("<h2>과제</h2>")
        for t in tasks:
            due = f" · {esc(t['due_text'])}" if t["due_text"] else ""
            done = " (완료)" if t["done"] else ""
            parts.append(f"<h3>{esc(t['title'])}{done}</h3><p class='muted small'>{TASK_KINDS.get(t['kind'], '')}{due}</p>"
                         f"<p>{esc(t['instructions'])}</p>")

    if parts:
        sections.append(parts)
    if sections:
        sections[0] = head + sections[0]
    else:
        sections = [head + ["<p>아직 정리할 내용이 없어요.</p>"]]

    for name, data in images.items():
        archive.add(data, name)
    out = io.BytesIO()
    writer = pymupdf.DocumentWriter(out)
    where = A4 + (MARGIN, MARGIN, -MARGIN, -MARGIN)
    # 슬라이드마다 새 쪽에서 시작한다 (제목과 슬라이드 그림이 갈라지지 않게)
    for section in sections:
        story = pymupdf.Story(html="<body>" + "".join(section) + "</body>", user_css=CSS, archive=archive)
        more = True
        while more:
            device = writer.begin_page(A4)
            more, _ = story.place(where)
            story.draw(device)
            writer.end_page()
    writer.close()

    # 쪽 번호
    doc = pymupdf.open("pdf", out.getvalue())
    for i, page in enumerate(doc, start=1):
        page.insert_text((A4.width / 2 - 10, A4.height - 18), f"{i} / {len(doc)}", fontsize=8, color=(0.6, 0.6, 0.6))
    doc.subset_fonts()
    return doc.tobytes(garbage=3, deflate=True)
