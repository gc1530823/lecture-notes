"""실제 녹음 하나를 끝까지 정리한다: 강의자료 PDF + 녹음 파일 → 받아쓰기·필기·과제·요약·퀴즈·정리 PDF.

결과는 out 폴더에 남긴다: 정리.pdf, 받아쓰기.txt, 필기.txt, 요약·퀴즈.json, 과제.json, 기록.txt
사용법 (server 폴더에서, 서버가 켜져 있을 때):
  python scripts/process_recording.py 강의자료.pdf 녹음.m4a out [--url http://localhost:8000]
"""

import argparse
import json
import os
import time

import httpx


def log(out: str, message: str) -> None:
    print(message, flush=True)
    with open(os.path.join(out, "기록.txt"), "a") as f:
        f.write(message + "\n")


def wait_for(http: httpx.Client, path: str, done, out: str, label: str, started: float) -> dict:
    last = None
    while True:
        res = http.get(path).raise_for_status().json()
        state = (res.get("status"), res.get("progress"), res.get("done"))
        if state != last:
            extra = f" {res['progress']:.0%}" if res.get("progress") else ""
            extra += f" {res['done']}/{res['total']}쪽" if res.get("total") else ""
            log(out, f"  [{time.monotonic() - started:6.0f}초] {label}: {res.get('status')}{extra}")
            last = state
        if done(res):
            return res
        time.sleep(3)


def main(pdf: str, audio: str, out: str, base: str) -> None:
    os.makedirs(out, exist_ok=True)
    started = time.monotonic()
    with httpx.Client(base_url=base, timeout=600) as http:
        log(out, f"서버: {http.get('/health').json()}")
        title = os.path.splitext(os.path.basename(pdf))[0]
        with open(pdf, "rb") as f:
            doc = http.post("/documents", files={"file": (os.path.basename(pdf), f, "application/pdf")},
                            data={"title": title}).raise_for_status().json()
        log(out, f"강의자료: {title} ({len(doc['pages'])}쪽)")
        with open(audio, "rb") as f:
            session = http.post("/sessions/from-audio", data={"document_id": doc["id"]},
                                files={"file": (os.path.basename(audio), f)}).raise_for_status().json()
        log(out, f"녹음 파일: {os.path.getsize(audio) / 1e6:.1f}MB")
        result = wait_for(http, f"/sessions/{session['id']}/summary", lambda r: r["status"] in ("done", "failed"),
                          out, "정리", started)

        sid = session["id"]
        segments = http.get(f"/sessions/{sid}/transcript").json()
        with open(os.path.join(out, "받아쓰기.txt"), "w") as f:
            for s in segments:
                m, sec = divmod(s["start_ms"] // 1000, 60)
                f.write(f"[{m:02d}:{sec:02d}] ({s['page_no'] or '?'}쪽) {s['text']}\n")
        notes = http.get(f"/sessions/{sid}/annotations").json()
        with open(os.path.join(out, "필기.txt"), "w") as f:
            for a in notes:
                where = "보류함" if a["pending"] else f"{a['page_no']}쪽"
                f.write(f"[{where}] ({a['type']}) {a['text']}\n")
        tasks = http.get(f"/sessions/{sid}/tasks").json()
        with open(os.path.join(out, "과제.json"), "w") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
        with open(os.path.join(out, "요약·퀴즈.json"), "w") as f:
            json.dump(result.get("summary"), f, ensure_ascii=False, indent=2)
        log(out, f"받아쓰기 {len(segments)}문장 · 필기 {len(notes)}개 (보류함 {sum(a['pending'] for a in notes)}개) · "
                 f"과제 {len(tasks)}개 · 요약 {result['status']}")

        http.post(f"/sessions/{sid}/notes-pdf").raise_for_status()
        status = wait_for(http, f"/sessions/{sid}/notes-pdf/status", lambda r: r["status"] != "building",
                          out, "정리 PDF", started)
        if status["status"] == "ready":
            with open(os.path.join(out, "정리.pdf"), "wb") as f:
                f.write(http.get(f"/sessions/{sid}/notes-pdf").content)
        log(out, f"끝 · 전체 {time.monotonic() - started:.0f}초 · 정리 PDF {status['status']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("audio")
    parser.add_argument("out")
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    main(args.pdf, args.audio, args.out, args.url)
