"""받아쓰기 정확도: 우리 받아쓰기와 공식 자막(사람이 만든 것)을 같은 시간 구간에서 비교한다.

- WER(단어 오류율): 단어를 몇 개 바꾸거나 빼거나 더해야 자막과 같아지는지 ÷ 자막 단어 수. 낮을수록 좋다.
- 정확도 = 1 - WER (영어 강의는 단어 단위, 한국어는 띄어쓰기 단위)
- 전문용어 적중률: 슬라이드에 나온 용어 중 자막에 나온 것을 우리 받아쓰기도 맞게 적었는지

사용법: python scripts/score_transcript.py <자막 .srt/.vtt> <결과 폴더(받아쓰기.txt 가 있는 곳)> <분(앞부분만 쓴 경우)> [슬라이드.pdf]
"""

import os
import re
import sys


def caption_text(path: str, minutes: float) -> str:
    text = open(path, encoding="utf-8", errors="replace").read()
    limit = minutes * 60 if minutes > 0 else float("inf")
    out = []
    for block in re.split(r"\n\s*\n", text):
        times = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->", block)
        if not times:
            continue
        h, m, s, _ = (int(x) for x in times.groups())
        if h * 3600 + m * 60 + s > limit:
            break
        lines = [ln for ln in block.splitlines() if "-->" not in ln and not ln.strip().isdigit() and ln.strip()]
        out.append(re.sub(r"<[^>]+>", "", " ".join(lines)))
    return " ".join(out)


def words(text: str) -> list[str]:
    text = text.lower().replace("’", "'")
    return re.findall(r"[a-z0-9가-힣']+", text)


def wer(ref: list[str], hyp: list[str]) -> float:
    # 편집 거리 (메모리를 아끼려고 두 줄만)
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, start=1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / max(1, len(ref))


def main(captions: str, result: str, minutes: float, slides: str | None) -> None:
    ref_text = caption_text(captions, minutes)
    ours = open(os.path.join(result, "받아쓰기.txt"), encoding="utf-8").read()
    ours = re.sub(r"^\[[^\]]*\]\s*(\([^)]*\)\s*)?", "", ours, flags=re.M)  # "[01:23] (3쪽)" 머리 지우기
    ref, hyp = words(ref_text), words(ours)
    # 자막은 뒤가 조금 더 길거나 짧을 수 있으니 우리 받아쓰기 길이에 맞춰 자른다
    ref = ref[: int(len(hyp) * 1.05) + 10]
    error = wer(ref, hyp)
    lines = [f"받아쓰기 정확도 (공식 자막과 비교, 앞 {minutes:g}분)",
             f"- 자막 단어 {len(ref)}개 · 우리 받아쓰기 단어 {len(hyp)}개",
             f"- 단어 오류율(WER) {error:.1%} → 정확도 약 {max(0.0, 1 - error):.1%}"]
    if slides:
        import pymupdf

        slide_words = {w for page in pymupdf.open(slides) for w in words(page.get_text()) if len(w) >= 5}
        said = [w for w in slide_words if w in set(ref)]
        hit = [w for w in said if w in set(hyp)]
        if said:
            lines.append(f"- 슬라이드 용어 중 자막에 나온 {len(said)}개 가운데 {len(hit)}개를 맞게 받아씀 ({len(hit) / len(said):.0%})")
            missed = sorted(set(said) - set(hit))[:15]
            if missed:
                lines.append(f"  놓친 용어: {', '.join(missed)}")
    report = "\n".join(lines)
    print(report)
    with open(os.path.join(result, "정확도.txt"), "w", encoding="utf-8") as f:
        f.write(report + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4] if len(sys.argv) > 4 else None)
