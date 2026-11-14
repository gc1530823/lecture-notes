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
_lock = threading.Lock()
_model: tuple | None = None
_failed = False


def _model_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.upload_dir)), "ocr-korean")


def _download(name: str) -> str:
    import httpx

    path = os.path.join(_model_dir(), name)
    if not os.path.exists(path):
        os.makedirs(_model_dir(), exist_ok=True)
        with httpx.stream("GET", REPO + name, follow_redirects=True, timeout=120) as r:
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
    new_w = max(16, min(1600, int(round(w * 48 / h))))
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
