"""쪽 추적 정답 만들기·채점: 강의 영상에 비친 화면과 강의자료 PDF 쪽을 그림으로 비교해 "그 순간 실제 몇 쪽이었는지"를 찾고,
우리 받아쓰기(받아쓰기.txt 의 [mm:ss] (N쪽))가 그 쪽에 맞게 붙었는지 잰다.

- 영상을 2초마다 64×48 흑백으로 줄이고, PDF 쪽도 같은 크기로 줄여 모양이 얼마나 같은지(정규화 상관) 비교한다.
- 모든 쪽에 공통인 바탕을 빼고 비교해, 가장 닮은 쪽이 충분히 닮았고(0.35 이상) 둘째보다 확실히 닮았을 때(0.12 이상 차이)만 정답으로 쓴다.
  화면에 교수님만 나오는 장면은 정답에서 빠진다 (그 시간은 채점하지 않음).
- 문장 시각의 정답 쪽 = 그 시각 앞뒤로 가장 가까운 정답 장면의 쪽.

사용법: python scripts/slide_truth.py <영상.mp4> <강의자료.pdf> <결과 폴더> [분]
결과: 결과 폴더/쪽정답.json, 정확도.txt 에 "쪽 추적" 줄을 덧붙인다.
"""

import json
import os
import re
import subprocess
import sys

import numpy as np

W, H = 64, 48
STEP = 2.0  # 초


def video_frames(path: str, minutes: float) -> np.ndarray:
    args = ["ffmpeg", "-loglevel", "error", "-i", path]
    if minutes > 0:
        args += ["-t", str(minutes * 60)]
    args += ["-vf", f"fps={1 / STEP},scale={W}:{H},format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(args, check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, H, W).astype(np.float32)


def pdf_pages(path: str) -> np.ndarray:
    import pymupdf

    pages = []
    for page in pymupdf.open(path):
        pix = page.get_pixmap(matrix=pymupdf.Matrix(4 * W / page.rect.width, 4 * H / page.rect.height), colorspace=pymupdf.csGRAY)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)[: 4 * H, : 4 * W].astype(np.float32)
        img = np.pad(img, ((0, 4 * H - img.shape[0]), (0, 4 * W - img.shape[1])), mode="edge")
        pages.append(img.reshape(H, 4, W, 4).mean(axis=(1, 3)))
    return np.stack(pages)


def trim_bars(frame: np.ndarray) -> np.ndarray:
    """영상 위아래·좌우의 검은 띠(화면비가 달라 생긴 것)를 잘라 내고 다시 64×48로."""
    rows = np.where(frame.mean(axis=1) > 40)[0]
    cols = np.where(frame.mean(axis=0) > 40)[0]
    if len(rows) < H // 2 or len(cols) < W // 2:
        return frame
    cut = frame[rows[0]: rows[-1] + 1, cols[0]: cols[-1] + 1]
    ys = np.linspace(0, cut.shape[0] - 1, H).astype(int)
    xs = np.linspace(0, cut.shape[1] - 1, W).astype(int)
    return cut[np.ix_(ys, xs)]


def normalize(a: np.ndarray) -> np.ndarray:
    a = a.reshape(len(a), -1) if a.ndim >= 2 else a.reshape(1, -1)
    a = a - a.mean(axis=1, keepdims=True)
    return a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-6)


def blur(a: np.ndarray) -> np.ndarray:
    """3×3 평균 흐림: 영상은 압축으로 흐려져 있으니 PDF 쪽도 비슷하게 흐려 맞춘다"""
    padded = np.pad(a, ((0, 0), (1, 1), (1, 1)), mode="edge")
    return sum(padded[:, dy:dy + H, dx:dx + W] for dy in range(3) for dx in range(3)) / 9


def match(frames: np.ndarray, pages: np.ndarray, min_score: float = 0.35, margin: float = 0.12) -> list[int | None]:
    """장면마다 정답 쪽 번호(1부터), 확실하지 않으면 None.
    모든 쪽에 공통인 바탕(제목 띠·로고·흰 여백)을 빼고 쪽마다 다른 부분끼리만 비교해야 쪽이 잘 갈린다."""
    pages = blur(pages)
    frames = blur(np.stack([trim_bars(x) for x in frames]))
    # 밝기 차이를 없애고 나서 공통 바탕을 뺀다
    def standardize(a):
        flat = a.reshape(len(a), -1)
        return (flat - flat.mean(axis=1, keepdims=True)) / (flat.std(axis=1, keepdims=True) + 1e-6)
    p, f = standardize(pages), standardize(frames)
    template = p.mean(axis=0, keepdims=True)
    p, f = normalize(p - template), normalize(f - template)
    scores = f @ p.T
    out: list[int | None] = []
    for row in scores:
        order = np.argsort(row)[::-1]
        best, second = row[order[0]], (row[order[1]] if len(order) > 1 else -1)
        out.append(int(order[0]) + 1 if best >= min_score and best - second >= margin else None)
    # 한 장면만 튀는 것은 앞뒤가 같으면 그 쪽으로
    for i in range(1, len(out) - 1):
        if out[i - 1] is not None and out[i - 1] == out[i + 1] and out[i] != out[i - 1]:
            out[i] = out[i - 1]
    return out


def truth_at(truth: list[int | None], seconds: float, window: float = 6.0) -> int | None:
    i = int(round(seconds / STEP))
    for d in range(0, int(window / STEP) + 1):
        for j in (i - d, i + d):
            if 0 <= j < len(truth) and truth[j] is not None:
                return truth[j]
    return None


def score(truth: list[int | None], transcript: str) -> dict:
    total = right = near = 0
    for line in transcript.splitlines():
        m = re.match(r"\[(\d+):(\d+)\]\s*\((\d+)쪽\)", line)
        if not m:
            continue
        t = int(m.group(1)) * 60 + int(m.group(2))
        ours, real = int(m.group(3)), truth_at(truth, t)
        if real is None:
            continue
        total += 1
        right += ours == real
        near += abs(ours - real) <= 1
    return {"sentences": total, "exact": right / total if total else None, "within_one": near / total if total else None}


def main(video: str, pdf: str, result: str, minutes: float) -> None:
    truth = match(video_frames(video, minutes), pdf_pages(pdf))
    known = sum(t is not None for t in truth)
    json.dump({"step_seconds": STEP, "pages": truth}, open(os.path.join(result, "쪽정답.json"), "w"))
    transcript_path = os.path.join(result, "받아쓰기.txt")
    lines = [f"쪽 추적 (영상 화면과 강의자료를 그림으로 맞춘 정답과 비교)",
             f"- 영상 장면 {len(truth)}개 중 슬라이드가 확실히 보인 장면 {known}개 ({known / max(1, len(truth)):.0%})"]
    if os.path.exists(transcript_path):
        s = score(truth, open(transcript_path, encoding="utf-8").read())
        if s["sentences"]:
            lines.append(f"- 채점한 문장 {s['sentences']}개: 정확히 맞은 쪽 {s['exact']:.0%} · 한 쪽 차이까지 {s['within_one']:.0%}")
        else:
            lines.append("- 슬라이드가 보인 시간에 받아쓴 문장이 없어 채점하지 못했어요")
    report = "\n".join(lines)
    print(report)
    with open(os.path.join(result, "정확도.txt"), "a", encoding="utf-8") as f:
        f.write("\n" + report + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else 0)
