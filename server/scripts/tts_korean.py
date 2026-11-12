"""한국어 강의 대본(script.json의 speech)을 무료 음성 합성(MeloTTS 한국어, MIT 라이선스)으로 읽어 녹음 파일을 만든다.

문장마다 따로 읽고 사이에 0.3~1.2초 쉼을 넣어 이어 붙인다. 문장마다 시작·끝 시각을 남겨서
받아쓰기 정답(자막)과 쪽 정답을 만들 수 있게 한다. 진짜 교수님보다 깨끗한 목소리라, 원하면 잡음과 빠르기 차이를 섞는다.

서버와 따로 도는 파이썬(MeloTTS가 옛 패키지에 묶여 있어 3.10 가상환경)에서 돌린다:
  python tts_korean.py script.json lecture.wav timings.json [--noise 0.004]
"""

import argparse
import json
import random

import numpy as np
import soundfile as sf


def main(script: str, wav: str, timings: str, noise: float, seed: int) -> None:
    from melo.api import TTS

    rng = random.Random(seed)
    speech = json.load(open(script, encoding="utf-8"))["speech"]
    model = TTS(language="KR", device="cpu")
    speaker = model.hps.data.spk2id["KR"]
    rate = model.hps.data.sampling_rate
    audio, out, t = [], [], 0.0
    for i, s in enumerate(speech):
        pause = rng.uniform(0.3, 1.2)
        audio.append(np.zeros(int(pause * rate), dtype=np.float32))
        t += pause
        clip = model.tts_to_file(s["text"], speaker, None, speed=rng.uniform(0.95, 1.2), quiet=True)
        clip = np.asarray(clip, dtype=np.float32)
        audio.append(clip)
        out.append({"start": round(t, 2), "end": round(t + len(clip) / rate, 2), "page_no": s["page_no"], "text": s["text"]})
        t += len(clip) / rate
        if i % 10 == 0:
            print(f"  읽는 중 {i + 1}/{len(speech)} ({t:.0f}초)", flush=True)
    full = np.concatenate(audio)
    if noise > 0:  # 강의실 잡음 비슷하게
        full = full + np.random.default_rng(seed).normal(0, noise, len(full)).astype(np.float32)
    sf.write(wav, full, rate)
    json.dump(out, open(timings, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"녹음 {t / 60:.1f}분 · 문장 {len(out)}개 → {wav}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("script"), p.add_argument("wav"), p.add_argument("timings")
    p.add_argument("--noise", type=float, default=0.004)
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    main(a.script, a.wav, a.timings, a.noise, a.seed)
