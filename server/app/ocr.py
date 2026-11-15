"""시간표 칸 안의 글(과목 이름·강의실)을 서버에서 직접 읽는다 — 사진 읽는 AI 가 없거나 실패할 때.

PaddleOCR 의 한국어 글자 인식 모델(korean_PP-OCRv5_mobile_rec, Apache-2.0, 약 10MB)을 처음 쓸 때 HuggingFace 에서 받아 둔다.
칸의 위치는 이미 알고 있으므로(timetable_image) 글자 찾기 모델 없이, 칸 안에서 글 줄을 직접 나눠 줄마다 인식만 한다.
onnxruntime 이 없거나 모델을 못 받으면 조용히 빈 결과 (이름은 사람이 적는다).
"""

from __future__ import annotations

import logging
import os
import re
import threading

import numpy as np

from .config import settings

log = logging.getLogger(__name__)
REPO = "https://huggingface.co/PaddlePaddle/korean_PP-OCRv5_mobile_rec_onnx/resolve/main/"
# 사진에서 글 줄의 자리를 찾는 모델 (PP-OCRv5_mobile_det, Apache-2.0, 약 5MB): 칠판·화이트보드·화면 사진 읽기에 쓴다
DET_REPO = "https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det_onnx/resolve/main/"
_lock = threading.Lock()
_model: tuple | None = None
_failed = False


def _model_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.upload_dir)), "ocr-korean")


def _download(name: str, repo: str = REPO, local: str = "") -> str:
    import httpx

    path = os.path.join(_model_dir(), local or name)
    if not os.path.exists(path):
        os.makedirs(_model_dir(), exist_ok=True)
        with httpx.stream("GET", repo + name, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with open(path + ".part", "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        os.replace(path + ".part", path)
    return path


def read_dict(yml_text: str) -> list[str]:
    """inference.yml 의 PostProcess.character_dict (줄마다 '  - 글자')"""
    lines = yml_text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip() == "character_dict:")
    out = []
    for l in lines[start + 1:]:
        m = re.match(r"^\s*- (.*)$", l)
        if not m:
            break
        ch = m.group(1)
        if len(ch) >= 2 and ch[0] == ch[-1] and ch[0] in "'\"":
            ch = ch[1:-1].replace("''", "'")
        out.append(ch)
    return out


def _load():
    global _model, _failed
    with _lock:
        if _model is not None or _failed:
            return _model
        if os.environ.get("OCR_DISABLED"):   # 시험(테스트)에서는 모델을 받지 않는다
            return None
        try:
            import onnxruntime as ort

            chars = read_dict(open(_download("inference.yml"), encoding="utf-8").read())
            sess = ort.InferenceSession(_download("inference.onnx"), providers=["CPUExecutionProvider"])
            _model = (sess, chars)
        except Exception:
            log.exception("한국어 글자 인식 모델을 쓸 수 없습니다 (시간표 이름은 사람이 적습니다)")
            _failed = True
        return _model


def decode(probs: np.ndarray, chars: list[str]) -> str:
    """CTC: 칸마다 가장 높은 것 → 이어서 같은 것은 하나로, 0(빈칸)은 버린다. 마지막 칸이 하나 더 있으면 띄어쓰기"""
    idx = probs.argmax(axis=-1)
    out, prev = [], -1
    for i in idx:
        if i != prev and i != 0:
            k = int(i) - 1
            out.append(chars[k] if k < len(chars) else " ")
        prev = i
    return "".join(out).strip()


def text_lines(crop: np.ndarray, bg: np.ndarray) -> list[np.ndarray]:
    """칸 안에서 글 줄 나누기: 칸 색과 많이 다른(진한) 점이 있는 가로줄을 묶는다"""
    diff = np.abs(crop.astype(np.int16) - bg.astype(np.int16)).max(axis=-1)
    ink = diff > 70
    rows = ink.sum(axis=1) > 0
    lines, y = [], 0
    h = len(rows)
    while y < h:
        if rows[y]:
            y0 = y
            while y < h and (rows[y] or (y + 1 < h and rows[y + 1]) or (y + 2 < h and rows[y + 2])):
                y += 1
            if y - y0 >= 6:
                cols = np.where(ink[y0:y].any(axis=0))[0]
                x0, x1 = max(0, cols[0] - 3), min(crop.shape[1], cols[-1] + 4)
                lines.append(crop[max(0, y0 - 3):min(h, y + 3), x0:x1])
        y += 1
    return lines


def _prep(line: np.ndarray) -> np.ndarray:
    import pymupdf

    h, w = line.shape[:2]
    new_w = max(16, min(3200, int(round(w * 48 / h))))   # 긴 줄(칠판 한 줄)도 줄이지 않게
    pix = pymupdf.Pixmap(pymupdf.csRGB, w, h, np.ascontiguousarray(line).tobytes(), False)
    # 가장 가까운 점으로 늘이고 줄이기 (pymupdf 만으로)
    ys = (np.arange(48) * h / 48).astype(int)
    xs = (np.arange(new_w) * w / new_w).astype(int)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(h, w, 3)[ys][:, xs]
    bgr = arr[:, :, ::-1].astype(np.float32) / 255.0
    return ((bgr - 0.5) / 0.5).transpose(2, 0, 1)[None]


def read_block(rgb: np.ndarray, box: tuple[int, int, int, int], bg: list[int]) -> list[str]:
    """칸 하나의 글 줄들 (위에서부터)"""
    model = _load()
    if model is None:
        return []
    sess, chars = model
    x0, y0, x1, y1 = box
    crop = rgb[y0 + 2:y1 - 1, x0 + 2:x1 - 1]
    out = []
    for line in text_lines(crop, np.array(bg))[:5]:
        try:
            probs = sess.run(None, {sess.get_inputs()[0].name: _prep(line)})[0][0]
            text = decode(probs, chars)
            if text:
                out.append(text)
        except Exception:
            log.exception("글 줄 인식 실패")
    return out


ROOM = re.compile(r"^[가-힣A-Za-z]{0,4}\s?-?\d{2,4}[A-Za-z]?호?$")


def name_and_place(lines: list[str]) -> tuple[str, str]:
    """'설비시계열이', '상탐지·예측', '정204' → ('설비시계열이상탐지·예측', '정204'). 한 칸에 이름이 여러 줄로 감긴다"""
    name, place = [], ""
    for line in lines:
        if not place and name and ROOM.match(line.replace(" ", "")):
            place = line.replace(" ", "")
            break
        name.append(line)
    return "".join(name).strip()[:40], place[:40]


# ───────── 사진 읽기 (칠판·화이트보드·화면 사진): 글 줄 찾기 → 줄마다 읽기 ─────────
_det = None
_det_failed = False


def _load_det():
    global _det, _det_failed
    with _lock:
        if _det is not None or _det_failed:
            return _det
        if os.environ.get("OCR_DISABLED"):
            return None
        try:
            import onnxruntime as ort

            _det = ort.InferenceSession(_download("inference.onnx", DET_REPO, "det.onnx"), providers=["CPUExecutionProvider"])
        except Exception:
            log.exception("글 줄 찾기 모델을 쓸 수 없습니다")
            _det_failed = True
        return _det


def _decode_image(data: bytes) -> np.ndarray:
    """jpg·png 바이트 → RGB 배열 (pymupdf 만으로)"""
    import pymupdf

    pix = pymupdf.Pixmap(data)
    if pix.alpha or pix.n != 3:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix, 0) if pix.n != 3 else pix
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].copy()


def _resize(rgb: np.ndarray, h: int, w: int) -> np.ndarray:
    ys = (np.arange(h) * rgb.shape[0] / h).astype(int)
    xs = (np.arange(w) * rgb.shape[1] / w).astype(int)
    return rgb[ys][:, xs]


def components(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    """참인 칸끼리 이어진 덩어리마다 (x0, y0, x1, y1, 칸 수). 줄마다 이어진 구간을 찾고 윗줄 구간과 겹치면 합친다"""
    parent: list[int] = []

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    runs = []          # (y, x0, x1, id)
    prev: list[tuple[int, int, int]] = []
    for y in range(mask.shape[0]):
        row = mask[y]
        if not row.any():
            prev = []
            continue
        d = np.diff(np.concatenate(([0], row.view(np.uint8), [0])).astype(np.int8))
        starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        cur = []
        j = 0
        for x0, x1 in zip(starts.tolist(), ends.tolist()):
            rid = len(parent); parent.append(rid)
            while j < len(prev) and prev[j][1] <= x0:
                j += 1
            k = j
            while k < len(prev) and prev[k][0] < x1:
                ra, rb = find(rid), find(prev[k][2])
                if ra != rb:
                    parent[ra] = rb
                k += 1
            cur.append((x0, x1, rid)); runs.append((y, x0, x1, rid))
        prev = cur
    boxes: dict[int, list[int]] = {}
    for y, x0, x1, rid in runs:
        r = find(rid)
        b = boxes.get(r)
        if b is None:
            boxes[r] = [x0, y, x1, y + 1, x1 - x0]
        else:
            b[0] = min(b[0], x0); b[1] = min(b[1], y); b[2] = max(b[2], x1); b[3] = y + 1; b[4] += x1 - x0
    return [tuple(b) for b in boxes.values()]


def reading_order(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """위에서 아래로 줄을 나누고, 같은 줄은 왼쪽부터"""
    rows: list[list[tuple[int, int, int, int]]] = []
    for b in sorted(boxes, key=lambda b: (b[1] + b[3]) / 2):
        cy, h = (b[1] + b[3]) / 2, b[3] - b[1]
        if rows:
            last = rows[-1]
            ly = sum((r[1] + r[3]) / 2 for r in last) / len(last)
            lh = sum(r[3] - r[1] for r in last) / len(last)
            if abs(cy - ly) < 0.5 * min(h, lh):
                last.append(b); continue
        rows.append([b])
    return [b for row in rows for b in sorted(row, key=lambda b: b[0])]


def read_photo(data: bytes, limit: int = 60) -> list[str]:
    """사진 속 글 줄을 위에서부터 읽는다. 모델이 없거나 읽지 못하면 빈 목록"""
    det, rec = _load_det(), _load()
    if det is None or rec is None:
        return []
    sess, chars = rec
    rgb = _decode_image(data)
    H, W = rgb.shape[:2]
    scale = min(1.0, 960 / max(H, W))
    h, w = max(32, int(round(H * scale / 32)) * 32), max(32, int(round(W * scale / 32)) * 32)
    small = _resize(rgb, h, w)
    bgr = small[:, :, ::-1].astype(np.float32) / 255.0
    x = ((bgr - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)).transpose(2, 0, 1)[None]
    prob = det.run(None, {det.get_inputs()[0].name: x})[0][0, 0]
    boxes = []
    for x0, y0, x1, y1, area in components(prob > 0.3):
        if (x1 - x0) < 3 or (y1 - y0) < 3:
            continue
        if float(prob[y0:y1, x0:x1].mean()) < 0.3 and area < 20:
            continue
        # DB 모델은 글자보다 조금 좁게 잡으므로 넓혀 준다 (unclip 1.5 와 비슷하게)
        pad = int(round(area * 1.5 / max(1, 2 * ((x1 - x0) + (y1 - y0)))))
        sx, sy = W / w, H / h
        boxes.append((max(0, int((x0 - pad) * sx)), max(0, int((y0 - pad) * sy)), min(W, int((x1 + pad) * sx)), min(H, int((y1 + pad) * sy))))
    out = []
    for x0, y0, x1, y1 in reading_order(boxes)[:limit]:
        crop = rgb[y0:y1, x0:x1]
        if crop.shape[0] < 6 or crop.shape[1] < 6:
            continue
        if crop.shape[0] > crop.shape[1] * 1.5:   # 세로로 긴 덩어리(그림·선)는 건너뛴다
            continue
        try:
            text = decode(sess.run(None, {sess.get_inputs()[0].name: _prep(crop)})[0][0], chars).strip()
        except Exception:
            log.exception("사진 글 줄 읽기 실패")
            continue
        if text:
            out.append(text)
    return out
