"""iPhone 앱 대신 강의 한 번을 흉내 낸다: PDF 업로드 → 녹음(받아쓰기 전송) → 필기 수신 → 요약·퀴즈.

사용법: 서버를 켠 뒤 `.venv/bin/python scripts/simulate_lecture.py [http://localhost:8000]`
"""

import asyncio
import json
import sys

import httpx
import pymupdf
import websockets

SLIDES = [
    ["경사하강법 (Gradient Descent)", "손실 함수의 기울기 반대 방향으로 이동", "학습률 η가 이동 크기를 정한다"],
    ["역전파 (Backpropagation)", "연쇄 법칙으로 기울기를 계산", "출력층에서 입력층 방향으로 전달"],
]

# (교수님이 실제로 설명 중인 페이지 — 참고용, 서버에는 보내지 않음, 교수님 발언)
SPEECH = [
    (1, "자 오늘은 경사하강법부터 볼게요. 산에서 눈을 감고 내려간다고 생각하면 돼요."),
    (1, "학습률이 너무 크면 최솟값을 지나쳐서 발산하고, 너무 작으면 학습이 엄청 느려집니다."),
    (1, "이거 중간고사에 꼭 나와요. 학습률이 클 때와 작을 때 차이, 꼭 기억하세요."),
    (2, "다음 장, 역전파입니다. 결국 연쇄 법칙을 반복해서 쓰는 거예요."),
    (2, "과제 2번은 역전파를 손으로 직접 계산해 보는 거고 다음 주 금요일까지 제출입니다."),
]


def make_pdf() -> bytes:
    doc = pymupdf.open()
    for lines in SLIDES:
        page = doc.new_page(width=960, height=540)
        for i, line in enumerate(lines):
            size = 32 if i == 0 else 22
            page.insert_text((60, 90 + i * 70), line, fontname="korea", fontsize=size)
    return doc.tobytes()


async def main(base: str) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=120) as http:
        doc = (await http.post("/documents", files={"file": ("ml.pdf", make_pdf(), "application/pdf")},
                               data={"title": "머신러닝 3주차"})).raise_for_status().json()
        print(f"[업로드] {doc['title']} · {doc['page_count']}쪽 · 용어 {doc['keywords'][:6]}")
        blocks = {b["id"]: b["text"] for p in doc["pages"] for b in p["blocks"]}

        session = (await http.post("/sessions", json={"document_id": doc["id"]})).raise_for_status().json()
        ws_url = base.replace("http", "ws", 1) + f"/sessions/{session['id']}/stream"

        async with websockets.connect(ws_url) as ws:
            async def listen():
                async for raw in ws:
                    event = json.loads(raw)
                    if event["type"] == "page_estimate":
                        if event["page"] != state.get("page"):
                            state["page"] = event["page"]
                            print(f"  [자동 추적] 지금 {event['page']}쪽 설명 중 (확신 {event['confidence']:.2f})")
                    elif event["type"] == "annotation_added":
                        a = event["annotation"]
                        where = blocks.get(a["block_id"], "페이지 여백")
                        tag = "보류함" if a["pending"] else f"p.{a['page_no']}"
                        print(f"  [필기 {tag}] ({a['type']}) {a['text']}  ← \"{where}\" 옆")
                    else:
                        print(f"  [서버] {event}")

            state: dict = {}
            listener = asyncio.create_task(listen())
            # 학생은 1쪽을 펴 두기만 하고 넘기지 않는다: 페이지는 서버가 받아쓰기로 추적한다
            await ws.send(json.dumps({"type": "page_view", "page": 1, "initial": True}))
            for i, (_, text) in enumerate(SPEECH):
                print(f"[받아쓰기] {text}")
                start = i * 8000
                await ws.send(json.dumps({"type": "transcript_final", "text": text,
                                          "start_ms": start, "end_ms": start + 6000}))
                await asyncio.sleep(1)
            await ws.send(json.dumps({"type": "flush"}))
            await asyncio.sleep(20 if "fake" not in (await http.get("/health")).text else 2)
            listener.cancel()

        await http.post(f"/sessions/{session['id']}/end")
        print("[강의 종료] 요약·퀴즈 생성 중…")
        for _ in range(120):
            result = (await http.get(f"/sessions/{session['id']}/summary")).json()
            if result["status"] in ("done", "failed"):
                break
            await asyncio.sleep(2)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"))
