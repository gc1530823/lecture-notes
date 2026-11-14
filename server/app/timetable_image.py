"""시간표 캡처(에브리타임·학교 포털)에서 수업 칸의 '위치'를 그림으로 직접 잰다.

사진 읽는 AI 는 과목 이름은 잘 읽지만, 칸이 몇 시 몇 분에 시작하는지는 자주 틀린다 (특히 30분 단위, 오후 1시 = '1').
그래서 시각은 표의 줄(가로선 = 한 시간)과 색 칸의 위아래 위치로 계산하고, AI 에게서는 과목 이름·강의실만 받아 맞춘다.
AI 가 안 되면 칸과 시각만이라도 돌려준다 (이름은 사람이 적는다).
"""

from __future__ import annotations

import numpy as np
import pymupdf


def load_rgb(data: bytes) -> np.ndarray:
    pix = pymupdf.Pixmap(data)
    if pix.alpha or pix.n != 3:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix, False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)


def _colored(rgb: np.ndarray) -> np.ndarray:
    """수업 칸 색: 채도가 있고 너무 어둡지 않은 색 (배경 흰색·검은색·회색 선·검은 글씨는 아니다)"""
    rgb = rgb.astype(np.int16)
    hi, lo = rgb.max(axis=-1), rgb.min(axis=-1)
    return (hi - lo > 22) & (hi > 95)


def _lines(lum: np.ndarray, colored: np.ndarray, axis: int, min_frac: float) -> list[int]:
    """표의 선 찾기: 양옆보다 조금 밝거나(어두운 화면) 어두운(밝은 화면) 줄이 길게 이어지는 곳"""
    a = lum if axis == 1 else lum.T          # axis=1: 세로선(x 마다), axis=0: 가로선(y 마다)
    c = colored if axis == 1 else colored.T
    # 선 = 양옆 둘 다보다 밝거나(어두운 화면) 둘 다보다 어두운(밝은 화면) 가는 줄.
    # 칸 가장자리는 한쪽만 다르므로 선이 아니다
    one, two = a - np.roll(a, 2, axis=1), a - np.roll(a, -2, axis=1)
    hit = (((one > 4) & (two > 4)) | ((one < -4) & (two < -4))) & ~c
    frac = hit.mean(axis=0)
    xs = np.where(frac > min_frac)[0]
    out: list[int] = []
    for x in xs:
        if out and x - out[-1][-1] <= 3:
            out[-1].append(int(x))
        else:
            out.append([int(x)])
    return [int(round(sum(g) / len(g))) for g in out if 3 <= g[0] < a.shape[1] - 3]


def find_blocks(data: bytes) -> dict | None:
    """칸들: [{day, top, bottom, color}] (top·bottom = 첫 시각 줄에서 몇 시간 아래인지), 못 찾으면 None"""
    try:
        rgb = load_rgb(data)
    except Exception:
        return None
    h, w, _ = rgb.shape
    lum = rgb.astype(np.float32).mean(axis=-1)
    colored = _colored(rgb)

    vx = _lines(lum, colored, axis=1, min_frac=0.22)
    if len(vx) < 3:
        return None
    gaps = [(a, b) for a, b in zip(vx, vx[1:]) if b - a > w * 0.04]
    if not gaps:
        return None
    # 요일 칸은 너비가 같다: 칸에 가려 선 하나를 못 찾으면 두 칸이 한 칸처럼 보이므로 보통 너비로 나눈다
    widths = sorted(b - a for a, b in gaps)
    big = [x for x in widths if x > widths[-1] * 0.35]
    usual = min(big, key=lambda x: sum(abs(y / x - max(1, round(y / x))) for y in big))
    days = []
    for a, b in gaps:
        n = round((b - a) / usual)
        if (b - a) < usual * 0.6 or n < 1:
            continue          # 왼쪽 시각 칸
        step = (b - a) / n
        days += [(int(a + i * step), int(a + (i + 1) * step)) for i in range(n)]
    if not 1 <= len(days) <= 7:
        return None

    x0, x1 = days[0][0], days[-1][1]
    band = lum[:, x0:x1]
    hy = _lines(band, colored[:, x0:x1], axis=0, min_frac=0.3)
    diffs = [b - a for a, b in zip(hy, hy[1:]) if b - a > h * 0.015]
    if len(diffs) < 2:
        return None
    usual_gap = float(np.median(diffs))
    near_hour = [d for d in diffs if abs(d - usual_gap) < usual_gap * 0.2]
    hour = float(np.mean(near_hour))  # 선 굵기 때문에 1px 씩 흔들리므로 평균
    rows = [y for y, nxt in zip(hy, hy[1:]) if abs((nxt - y) - hour) < hour * 0.2]
    if not rows:
        return None
    first, bottom = rows[0], hy[-1]

    blocks = []
    for day, (a, b) in enumerate(days):
        xs = [int(a + (b - a) * f) for f in (0.80, 0.85, 0.90, 0.94, 0.97)]
        seg = None   # [시작 y, 끝 y, 색 합, 줄 수]
        gap = 0
        other = 0    # 다른 색이 몇 줄째 이어지는지 (글자 가장자리의 섞인 색은 몇 줄뿐이라 무시)
        for y in range(first, bottom):
            cs = [rgb[y, x].astype(np.float32) for x in xs if colored[y, x]]
            if len(cs) >= 2:
                col = np.median(cs, axis=0)
                if seg and np.abs(col - seg[2] / seg[3]).max() > 28:
                    other += 1
                    if other >= 6:   # 색이 정말 바뀌었다 = 붙어 있는 다른 수업
                        seg[1] = y - other
                        blocks.append(_block(day, seg, first, hour))
                        seg, other = [y - other + 1, y, col * other, other], 0
                    gap = 0
                    continue
                other = 0
                if seg is None:
                    seg = [y, y, col.copy(), 1]
                else:
                    seg[1] = y; seg[2] += col; seg[3] += 1
                gap = 0
            elif seg:
                gap += 1
                if gap > 6:
                    blocks.append(_block(day, seg, first, hour)); seg = None; gap = 0
        if seg:
            blocks.append(_block(day, seg, first, hour))
    blocks = [bl for bl in blocks if bl["bottom"] - bl["top"] > 0.3]
    return {"days": len(days), "blocks": blocks} if blocks else None


def _block(day: int, seg: list, first: int, hour: float) -> dict:
    return {"day": day, "top": (seg[0] - first) / hour, "bottom": (seg[1] + 1 - first) / hour,
            "color": [int(c) for c in seg[2] / seg[3]]}


def _clock(minutes: float) -> str:
    m = int(round(minutes / 5) * 5)
    return f"{m // 60:02d}:{m % 60:02d}"


def _hours(clock: str) -> float:
    h, m = clock.split(":")
    return int(h) + int(m) / 60


def combine(found: dict | None, ai_rows: list[dict]) -> list[dict]:
    """잰 칸(시각이 정확) + AI 가 읽은 목록(이름이 정확) → 수업 목록. 이름을 못 찾은 칸은 course 가 ''"""
    if not found:
        return ai_rows
    blocks = found["blocks"]
    # 첫 줄이 몇 시인지: 후보 시각(6~12시)마다 AI 가 읽은 시작 시각이 칸 위치와 몇 개 맞는지 센다.
    # 여러 개가 맞아야 믿는다 (AI 가 한두 개 틀려도 흔들리지 않게). 아니면 대학 시간표의 보통 시작인 9시
    def matches(base: int) -> int:
        n = 0
        for r in ai_rows:
            starts = (_hours(r["start"]), _hours(r["start"]) + 12)   # '1:30' 을 오전으로 읽었을 수도
            if any(bl["day"] == r["weekday"] and abs(st - base - bl["top"]) < 0.2 for bl in blocks for st in starts):
                n += 1
        return n
    scores = {b: matches(b) for b in range(6, 13)}
    best = max(scores, key=lambda b: (scores[b], b == 9))
    base = best if scores[best] >= max(2, len(ai_rows) * 0.4) else 9

    out, used = [], set()
    for bl in sorted(blocks, key=lambda b: (b["day"], b["top"])):
        start, end = base * 60 + bl["top"] * 60, base * 60 + bl["bottom"] * 60
        best, score = None, 1.6
        for i, r in enumerate(ai_rows):
            if i in used or r["weekday"] != bl["day"]:
                continue
            d = min(abs(_hours(r["start"]) - start / 60), abs(_hours(r["start"]) + 12 - start / 60))
            if d < score:
                best, score = i, d
        name, place = ("", "")
        if best is not None:
            used.add(best)
            name, place = ai_rows[best]["course"], ai_rows[best]["place"]
        out.append({"course": name, "weekday": bl["day"], "start": _clock(start), "end": _clock(min(end, 24 * 60 - 5)),
                    "place": place})
    # 칸을 하나도 못 찾은 요일에서 AI 가 읽은 것은 그대로 더한다
    seen_days = {bl["day"] for bl in blocks}
    out += [r for i, r in enumerate(ai_rows) if i not in used and r["weekday"] not in seen_days]
    return sorted(out, key=lambda c: (c["weekday"], c["start"]))
