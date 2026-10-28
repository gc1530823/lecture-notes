"""iPhone 앱 대신 강의 한 번을 흉내 낸다: PDF 업로드 → 받아쓰기 전송 → 자동 페이지 추적 → 필기 수신 → 요약·퀴즈.

학생은 1쪽을 펴 두기만 하고 넘기지 않는다. 페이지는 서버가 받아쓰기로 추적한다.
끝에 페이지 추적 정확도와 필기가 뜨기까지 걸린 시간을 출력한다.

사용법: 서버를 켠 뒤 `.venv/bin/python scripts/simulate_lecture.py [--url http://localhost:8000] [--wait 20]`
"""

import argparse
import asyncio
import json
import time

import httpx
import pymupdf
import websockets

SLIDES = [
    ["경사하강법 (Gradient Descent)", "손실 함수의 기울기 반대 방향으로 이동", "학습률 η가 이동 크기를 정한다",
     "θ ← θ − η · ∇L(θ)"],
    ["역전파 (Backpropagation)", "연쇄 법칙으로 각 가중치의 기울기를 계산", "출력층에서 입력층 방향으로 오차를 전달"],
    ["과적합과 정규화", "학습 데이터에만 지나치게 맞춰지는 현상", "L2 정규화, 드롭아웃, 조기 종료"],
]

# (교수님이 실제로 설명 중인 페이지 — 정답 채점용이고 서버에는 보내지 않음, 교수님 발언)
SPEECH = [
    (1, "자 오늘은 경사하강법부터 볼게요. 산에서 눈을 감고 내려간다고 생각하면 돼요."),
    (1, "가장 가파른 쪽으로 한 걸음씩 내려가는 거죠. 그게 기울기 반대 방향이에요."),
    (1, "학습률이 너무 크면 최솟값을 지나쳐서 발산하고, 너무 작으면 학습이 엄청 느려집니다."),
    (1, "이거 중간고사에 꼭 나와요. 학습률이 클 때와 작을 때 차이, 꼭 기억하세요."),
    (2, "다음 장, 역전파입니다. 결국 연쇄 법칙을 반복해서 쓰는 거예요."),
    (2, "출력층에서 오차를 구하고 그걸 거꾸로 입력층 쪽으로 보내면서 기울기를 구해요."),
    (2, "과제 2번은 역전파를 손으로 직접 계산해 보는 거고 다음 주 금요일까지 제출입니다."),
    (3, "자 이제 과적합 이야기를 해 볼게요. 학습 데이터만 너무 잘 맞히는 상태예요."),
    (3, "시험 문제를 외워서 푸는 학생이랑 비슷해요. 처음 보는 문제는 못 풀죠."),
    (3, "그래서 드롭아웃은 학습할 때 뉴런 일부를 무작위로 꺼 버리는 거예요."),
    (3, "조기 종료는 검증 손실이 다시 올라가기 시작하면 학습을 멈추는 방법이고요."),
    (3, "정규화 세 가지 차이는 기말고사에 나올 수 있으니까 정리해 두세요."),
]


def make_pdf() -> bytes:
    doc = pymupdf.open()
    for lines in SLIDES:
        page = doc.new_page(width=960, height=540)
        for i, line in enumerate(lines):
            page.insert_text((60, 90 + i * 70), line, fontname="korea", fontsize=32 if i == 0 else 22)
    return doc.tobytes()


async def main(base: str, wait: float, pdf_out: str | None = None) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=600) as http:
        health = (await http.get("/health")).json()
        print(f"[서버] 모드 {health['llm_mode']} · 모델 {health.get('model')}")
        doc = (await http.post("/documents", files={"file": ("ml.pdf", make_pdf(), "application/pdf")},
                               data={"title": "머신러닝 3주차"})).raise_for_status().json()
        print(f"[업로드] {doc['title']} · {doc['page_count']}쪽 · 용어 {doc['keywords'][:6]}")
        blocks = {b["id"]: b["text"] for p in doc["pages"] for b in p["blocks"]}

        session = (await http.post("/sessions", json={"document_id": doc["id"]})).raise_for_status().json()
        ws_url = base.replace("http", "ws", 1) + f"/sessions/{session['id']}/stream"

        started = time.monotonic()
        sent_at: list[float] = []
        estimates: list[int | None] = []
        notes: list[dict] = []
        previews: list[float] = []

        async with websockets.connect(ws_url) as ws:
            async def listen():
                async for raw in ws:
                    event = json.loads(raw)
                    now = time.monotonic()
                    if event["type"] == "page_estimate":
                        estimates.append(event["page"])
                        print(f"  [자동 추적] {event['page']}쪽 (확신 {event['confidence']:.2f})")
                    elif event["type"] == "annotation_preview":
                        p = event["preview"]
                        first = next((t for t in sent_at if t - started >= p["start_ms"] / 1000 - 0.01), sent_at[-1])
                        previews.append(now - first)
                        print(f"  [즉시 필기 {p['type']}] {p['text']}  · {now - first:.1f}초")
                    elif event["type"] == "previews_resolved":
                        pass
                    elif event["type"] == "task_added":
                        t = event["task"]
                        print(f"  [과제 {t['kind']}] {t['title']} — {t['instructions']} ({t['due_text'] or '마감 없음'})")
                    elif event["type"] == "annotation_added":
                        a = event["annotation"]
                        # 필기 묶음의 첫 문장을 보낸 시각부터 필기를 받은 시각까지
                        first = next((t for t in sent_at if t - started >= a["start_ms"] / 1000 - 0.01), sent_at[-1])
                        a["latency"] = now - first
                        notes.append(a)
                        where = "보류함" if a["pending"] else f"p.{a['page_no']} \"{blocks.get(a['block_id'], '페이지 여백')}\" 옆"
                        print(f"  [필기 {a['type']}] {a['text']}  → {where} · {a['latency']:.1f}초")
                    else:
                        print(f"  [서버] {event}")

            listener = asyncio.create_task(listen())
            await ws.send(json.dumps({"type": "page_view", "page": 1, "initial": True}))
            for _, text in SPEECH:
                start_ms = int((time.monotonic() - started) * 1000)
                sent_at.append(time.monotonic())
                print(f"[받아쓰기 {start_ms / 1000:5.1f}s] {text}")
                await ws.send(json.dumps({"type": "transcript_final", "text": text,
                                          "start_ms": start_ms, "end_ms": start_ms + 4000}))
                await asyncio.sleep(1.5)
            await ws.send(json.dumps({"type": "flush"}))
            await asyncio.sleep(wait)
            listener.cancel()

        await http.post(f"/sessions/{session['id']}/end")
        print("[강의 종료] 요약·퀴즈 생성 중…")
        for _ in range(300):
            result = (await http.get(f"/sessions/{session['id']}/summary")).json()
            if result["status"] in ("done", "failed"):
                break
            await asyncio.sleep(2)
        print(json.dumps(result, ensure_ascii=False, indent=2))

        if pdf_out:
            print("[정리 PDF] 페이지별 전체 정리 만드는 중…")
            started_pdf = time.monotonic()
            await http.post(f"/sessions/{session['id']}/notes-pdf")
            for _ in range(600):
                status = (await http.get(f"/sessions/{session['id']}/notes-pdf/status")).json()
                if status["status"] != "building":
                    break
                await asyncio.sleep(2)
            print(f"[정리 PDF] {status['status']} · {time.monotonic() - started_pdf:.0f}초")
            if status["status"] == "ready":
                with open(pdf_out, "wb") as f:
                    f.write((await http.get(f"/sessions/{session['id']}/notes-pdf")).content)

    # 채점
    truth = [page for page, _ in SPEECH]
    hits = sum(1 for want, got in zip(truth, estimates) if want == got)
    latencies = sorted(n["latency"] for n in notes)
    print("\n===== 결과 =====")
    print(f"페이지 추적 정확도: {hits}/{len(truth)} 문장")
    print(f"필기 {len(notes)}개 (보류함 {sum(n['pending'] for n in notes)}개), "
          f"종류 {sorted({n['type'] for n in notes})}")
    if previews:
        previews.sort()
        print(f"즉시 필기 {len(previews)}개, 지연: 중간값 {previews[len(previews) // 2]:.1f}초, 최대 {previews[-1]:.1f}초")
    if latencies:
        print(f"AI 필기 지연: 중간값 {latencies[len(latencies) // 2]:.1f}초, 최대 {latencies[-1]:.1f}초")
    print(f"요약 상태: {result['status']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--wait", type=float, default=5, help="마지막 문장 뒤 필기를 기다릴 시간(초)")
    parser.add_argument("--pdf-out", help="강의 정리 PDF를 저장할 경로 (주면 만들어 본다)")
    args = parser.parse_args()
    asyncio.run(main(args.url, args.wait, args.pdf_out))
