"""녹음 파일로 강의 정리하기를 끝까지 돌려 본다: 강의 문장을 합성 음성으로 읽혀 파일을 만들고 서버에 올린다.

필요: `pip install gTTS`, ffmpeg. 사용법: `python scripts/simulate_audio.py [--url http://localhost:8000]`
"""

import argparse
import difflib
import json
import os
import subprocess
import tempfile
import time

import httpx
from gtts import gTTS

from simulate_lecture import SPEECH, make_pdf


def make_audio(path: str) -> None:
    parts = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (_, text) in enumerate(SPEECH):
            part = os.path.join(tmp, f"{i:02d}.mp3")
            gTTS(text, lang="ko").save(part)
            parts.append(part)
        listing = os.path.join(tmp, "list.txt")
        with open(listing, "w") as f:
            f.writelines(f"file '{p}'\n" for p in parts)
        # 음성 메모처럼 m4a(AAC)로 만든다
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing,
                        "-c:a", "aac", "-b:a", "64k", path], check=True)


def main(base: str) -> None:
    audio = os.path.join(tempfile.mkdtemp(), "lecture.m4a")
    make_audio(audio)
    print(f"[녹음 파일] {os.path.getsize(audio) // 1024}KB")
    with httpx.Client(base_url=base, timeout=600) as http:
        doc = http.post("/documents", files={"file": ("ml.pdf", make_pdf(), "application/pdf")},
                        data={"title": "머신러닝 3주차"}).raise_for_status().json()
        started = time.monotonic()
        with open(audio, "rb") as f:
            session = http.post("/sessions/from-audio", data={"document_id": doc["id"]},
                                files={"file": ("lecture.m4a", f, "audio/mp4")}).raise_for_status().json()
        last = None
        while True:
            res = http.get(f"/sessions/{session['id']}/summary").json()
            state = (res["status"], res.get("progress"))
            if state != last:
                print(f"  [{time.monotonic() - started:6.1f}s] {res['status']} {res.get('progress') or ''}")
                last = state
            if res["status"] in ("done", "failed"):
                break
            time.sleep(3)

        segments = http.get(f"/sessions/{session['id']}/transcript").json()
        heard = " ".join(s["text"] for s in segments)
        truth = " ".join(text for _, text in SPEECH)
        ratio = difflib.SequenceMatcher(None, truth.replace(" ", ""), heard.replace(" ", "")).ratio()
        print("\n[받아쓰기]")
        for s in segments:
            print(f"  {s['start_ms'] / 1000:5.1f}s p.{s['page_no']} {s['text']}")
        notes = http.get(f"/sessions/{session['id']}/annotations").json()
        print("\n[필기]")
        for n in notes:
            print(f"  p.{n['page_no']} ({n['type']}) {n['text']}")
        for t in http.get(f"/sessions/{session['id']}/tasks").json():
            print(f"  [과제 {t['kind']}] {t['title']} ({t['due_text']})")
        print(json.dumps(res.get("summary"), ensure_ascii=False, indent=2)[:1500])
        print("\n===== 결과 =====")
        print(f"받아쓰기 글자 일치율: {ratio:.0%}")
        print(f"필기 {len(notes)}개, 페이지 {sorted({n['page_no'] for n in notes})}, 총 {time.monotonic() - started:.0f}초")
        print(f"상태: {res['status']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    main(parser.parse_args().url)
