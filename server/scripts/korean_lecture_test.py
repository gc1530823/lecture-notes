"""한국어 강의 시험: 대본을 우리가 만들었으니 '무슨 말을 몇 쪽에서 했는지' 정답이 정확히 있다.

  make  <폴더> [--seed N] : Groq로 한국어 강의(슬라이드 + 교수님 말투 대본)를 만들어 slides.pdf, script.json 저장
  truth <폴더>           : tts_korean.py가 남긴 timings.json → captions.vtt(받아쓰기 정답) · 쪽정답.json(쪽 정답)
  score <폴더> <결과 폴더> : 우리 받아쓰기(받아쓰기.txt)를 채점 → 결과 폴더의 정확도.txt
      - 글자 오류율(CER): 한국어는 띄어쓰기가 흔들려 단어 단위보다 글자 단위가 공정하다 (공백 빼고 비교)
      - 전문용어 적중률: 슬라이드 용어 중 대본에 나온 것을 받아쓰기도 맞게 적었는지
      - 쪽 추적: 문장마다 붙은 쪽이 정답 쪽과 같은지 (정확히 / 한 쪽 차이까지)
"""

import asyncio
import json
import os
import random
import re
import sys

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_synthetic_data import SUBJECTS, make_lecture, make_pdf  # noqa: E402

STEP = 2.0


async def make(folder: str, seed: int) -> None:
    os.makedirs(folder, exist_ok=True)
    rng = random.Random(seed)
    subject, topics = rng.choice(SUBJECTS)
    topic = rng.choice(topics)
    key = os.environ["GROQ_API_KEY"]
    async with httpx.AsyncClient(base_url="https://api.groq.com/openai/v1", timeout=180,
                                 headers={"Authorization": f"Bearer {key}"}) as groq:
        lecture = await make_lecture(groq, os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"), subject, topic,
                                     rng.randint(6, 9), rng.randint(60, 80))
    lecture["subject"], lecture["topic"] = subject, topic
    json.dump(lecture, open(os.path.join(folder, "script.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(folder, "slides.pdf"), "wb").write(make_pdf(lecture))
    open(os.path.join(folder, "name.txt"), "w").write(f"ko-{subject}-{topic}".replace(" ", "_")[:60])
    print(f"{subject} · {topic}: 슬라이드 {len(lecture['pages'])}장 · 문장 {len(lecture['speech'])}개")


def _clock(t: float) -> str:
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:06.3f}"


def truth(folder: str) -> None:
    timings = json.load(open(os.path.join(folder, "timings.json"), encoding="utf-8"))
    with open(os.path.join(folder, "captions.vtt"), "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for s in timings:
            f.write(f"{_clock(s['start'])} --> {_clock(s['end'])}\n{s['text']}\n\n")
    end = timings[-1]["end"] if timings else 0
    pages = [None] * (int(end / STEP) + 1)
    for s in timings:
        for i in range(int(s["start"] / STEP), int(s["end"] / STEP) + 1):
            pages[i] = s["page_no"]
    json.dump({"step_seconds": STEP, "pages": pages}, open(os.path.join(folder, "쪽정답.json"), "w"))


def _chars(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", text.lower())


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def score(folder: str, result: str) -> str:
    timings = json.load(open(os.path.join(folder, "timings.json"), encoding="utf-8"))
    lecture = json.load(open(os.path.join(folder, "script.json"), encoding="utf-8"))
    lines = [m for m in (re.match(r"\[(\d+):(\d+)\]\s*\((\d+)쪽\)\s*(.*)", l)
                         for l in open(os.path.join(result, "받아쓰기.txt"), encoding="utf-8")) if m]
    ref = _chars(" ".join(s["text"] for s in timings))
    hyp = _chars(" ".join(m[4] for m in lines))
    # 긴 글은 나눠서 (편집 거리 계산이 글자 수의 제곱이라)
    errors, n = 0, max(len(ref), 1)
    chunk = 1500
    for i in range(0, max(len(ref), len(hyp)), chunk):
        errors += edit_distance(ref[i:i + chunk], hyp[i:i + chunk])
    cer = errors / n

    terms = set()
    for page in lecture["pages"]:
        for bit in [page["title"], *page["bullets"]]:
            terms.update(w for w in re.findall(r"[가-힣]{2,}|[A-Za-z]{3,}", bit) if len(w) >= 2)
    said = [t for t in terms if _chars(t) and _chars(t) in ref]
    hit = [t for t in said if _chars(t) in hyp]

    def page_at(t: float) -> int | None:
        for s in timings:
            if s["start"] - 0.5 <= t <= s["end"] + 0.5:
                return s["page_no"]
        return None

    total = right = near = 0
    for m in lines:
        real = page_at(int(m[1]) * 60 + int(m[2]))
        if real is None:
            continue
        total += 1
        right += int(m[3]) == real
        near += abs(int(m[3]) - real) <= 1
    report = (f"한국어 강의 시험: {lecture.get('subject')} · {lecture.get('topic')} "
              f"(슬라이드 {len(lecture['pages'])}장, 녹음 {timings[-1]['end'] / 60:.1f}분)\n"
              f"- 받아쓰기 글자 오류율(CER) {cer:.1%} → 정확도 약 {1 - cer:.1%} (정답 {len(ref)}자 · 우리 {len(hyp)}자)\n"
              f"- 슬라이드 용어 중 대본에 나온 {len(said)}개 가운데 {len(hit)}개를 맞게 받아씀 ({len(hit) / max(len(said), 1):.0%})\n"
              f"  놓친 용어: {', '.join(sorted(set(said) - set(hit))[:15]) or '없음'}\n"
              f"- 쪽 추적: 채점한 문장 {total}개 · 정확히 맞은 쪽 {right / max(total, 1):.0%} · 한 쪽 차이까지 {near / max(total, 1):.0%}\n")
    open(os.path.join(result, "정확도.txt"), "w", encoding="utf-8").write(report)
    print(report)
    return report


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "make":
        asyncio.run(make(sys.argv[2], int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[3] == "--seed" else random.randrange(10**6)))
    elif cmd == "truth":
        truth(sys.argv[2])
    elif cmd == "score":
        score(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(__doc__)
