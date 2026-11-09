"""우리 AI의 첫 학습 데이터: 진짜 강의 녹음이 쌓이기 전에, 연습용 강의를 만들어 서버에 흘려보낸다.

1) Groq(큰 AI)에게 과목·주제를 주고 "강의자료 슬라이드 + 교수님이 실제로 말하듯 쓴 받아쓰기"를 만들게 한다.
   말투는 진짜 수업처럼: 슬라이드에 없는 예시·잡담, "이거 시험에 나와요", 과제 공지, 전문용어, 주제 넘어가기.
2) 슬라이드로 PDF를 만들어 서버에 올리고, 받아쓰기를 실시간 강의처럼 WebSocket으로 한 문장씩 보낸다.
   (몇 개는 강의자료 없는 노트 수업으로)
3) 강의를 끝내고 요약·플래시카드·개념·마인드맵·예상 문제·방금 뭐라고·따라잡기·튜터까지 한 번씩 부른다.

서버를 TRAINING_LOG=1 로 켜 두면 2)~3)에서 서버가 큰 AI에 보낸 요청과 답이 그대로 학습 데이터가 된다.
(1)의 강의 만들기 요청은 서버를 거치지 않으므로 학습 데이터에 섞이지 않는다)

사용법 (server 폴더, 서버를 TRAINING_LOG=1 로 켠 뒤):
  GROQ_API_KEY=... python scripts/make_synthetic_data.py --count 3 [--url http://localhost:8000]
"""

import argparse
import asyncio
import json
import os
import random
import time
import traceback

import httpx
import pymupdf
import websockets

FONT = os.path.join(os.path.dirname(__file__), "..", "app", "fonts", "NanumGothic.ttf")
FONT_BOLD = os.path.join(os.path.dirname(__file__), "..", "app", "fonts", "NanumGothicBold.ttf")

SUBJECTS = [
    ("인공지능개론", ["경사하강법과 학습률", "역전파", "과적합과 정규화", "합성곱 신경망", "트랜스포머와 어텐션"]),
    ("자료구조", ["이진 탐색 트리", "힙과 우선순위 큐", "해시 테이블", "그래프 탐색 BFS·DFS"]),
    ("운영체제", ["프로세스와 스레드", "교착 상태", "가상 메모리와 페이지 교체", "CPU 스케줄링"]),
    ("컴퓨터네트워크", ["TCP 혼잡 제어", "IP 주소와 서브넷", "HTTP와 웹의 동작"]),
    ("경영학원론", ["STP 전략", "마케팅 믹스 4P", "포터의 다섯 가지 힘", "조직 구조와 리더십"]),
    ("미시경제학", ["수요와 공급의 탄력성", "완전경쟁 시장", "독점과 가격 차별", "외부 효과"]),
    ("일반화학", ["화학 평형과 르샤틀리에 원리", "산과 염기", "오비탈과 전자 배치"]),
    ("일반물리학", ["뉴턴의 운동 법칙", "에너지 보존", "전기장과 가우스 법칙"]),
    ("생명과학", ["세포 호흡", "DNA 복제와 전사", "멘델 유전"]),
    ("심리학개론", ["고전적 조건형성", "기억의 단계", "인지 부조화"]),
    ("통계학", ["가설 검정과 p값", "중심극한정리", "회귀 분석"]),
    ("선형대수", ["고유값과 고유벡터", "행렬식", "벡터 공간과 기저"]),
    ("한국사", ["조선 후기 실학", "갑오개혁", "3·1 운동"]),
    ("법학개론", ["헌법의 기본 원리", "민법의 계약", "형법의 죄형법정주의"]),
    ("간호학개론", ["활력징후 측정", "감염 관리", "투약의 원칙"]),
]

LECTURE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "pages": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "bullets": {"type": "array", "items": {"type": "string"}}},
            "required": ["title", "bullets"], "additionalProperties": False}},
        "speech": {"type": "array", "items": {
            "type": "object",
            "properties": {"page_no": {"type": "integer"}, "text": {"type": "string"}},
            "required": ["page_no", "text"], "additionalProperties": False}},
    },
    "required": ["title", "pages", "speech"],
    "additionalProperties": False,
}

LECTURE_SYSTEM = """당신은 한국 대학의 교수입니다. 주어진 과목·주제로 강의 한 부분(약 10분)을 만듭니다.
- pages: 강의자료 슬라이드 {n}장. title은 짧은 제목, bullets는 슬라이드에 적힌 짧은 항목 2~5개 (용어는 영어를 괄호로 같이 써도 됨).
- speech: 교수님이 실제로 말한 것을 받아쓴 문장 {m}개쯤, 말한 순서대로. page_no는 그때 화면에 띄운 슬라이드 번호(1부터)이고 순서대로 넘어갑니다.
- 받아쓰기처럼 자연스러운 입말로 씁니다: "자, 그러면", "음", "여기 보시면" 같은 말, 문장이 길거나 끊기기도 함.
- 진짜 수업처럼 섞습니다: 슬라이드에 없는 예시·경험담·잡담, 같은 말 반복, 학생에게 묻기.
- 다음 중 일부를 자연스럽게 넣습니다: "이거 시험에 나와요"처럼 시험 언급 1~2번, 특히 강조하는 말, 과제나 공지 1번
  (예: "다음 주까지 ~해서 제출하세요"), 처음 나오는 전문용어를 풀어 주는 설명.
- 숫자·공식은 말로 읽듯이 씁니다. 사실과 다른 내용은 쓰지 않습니다."""


async def make_lecture(groq: httpx.AsyncClient, model: str, subject: str, topic: str, pages: int, sentences: int) -> dict:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": LECTURE_SYSTEM.format(n=pages, m=sentences)},
            {"role": "user", "content": f"과목: {subject}\n주제: {topic}"},
        ],
        "response_format": {"type": "json_schema", "json_schema": {"name": "lecture", "schema": LECTURE_SCHEMA}},
        "temperature": 0.9,
    }
    if "gpt-oss" in model:
        payload["reasoning_effort"] = "low"
    for attempt in range(6):
        res = await groq.post("/chat/completions", json=payload)
        if res.status_code == 429:
            wait = float(res.headers.get("retry-after", 20 * (attempt + 1)))
            print(f"    Groq 한도: {wait:.0f}초 기다림", flush=True)
            await asyncio.sleep(min(wait, 120))
            continue
        if res.status_code == 400 and attempt < 5:
            continue  # 스키마에 안 맞는 답 → 다시
        res.raise_for_status()
        lecture = json.loads(res.json()["choices"][0]["message"]["content"])
        lecture["pages"] = lecture["pages"][:12]
        lecture["speech"] = [s for s in lecture["speech"] if 1 <= s["page_no"] <= len(lecture["pages"]) and s["text"].strip()]
        return lecture
    raise RuntimeError("강의를 만들지 못했습니다")


def make_pdf(lecture: dict) -> bytes:
    doc = pymupdf.open()
    for page in lecture["pages"]:
        p = doc.new_page(width=960, height=540)
        p.insert_font(fontname="nb", fontfile=FONT_BOLD)
        p.insert_font(fontname="n", fontfile=FONT)
        p.insert_text((60, 90), page["title"][:40], fontname="nb", fontsize=32)
        y = 170
        for bullet in page["bullets"][:6]:
            # 긴 항목은 줄을 나눠 쓴다
            words, line = bullet.split(), ""
            for word in words:
                if len(line) + len(word) > 38:
                    p.insert_text((80, y), line, fontname="n", fontsize=22)
                    y, line = y + 34, ""
                line = f"{line} {word}".strip()
            p.insert_text((60, y), "•", fontname="n", fontsize=22)
            p.insert_text((80, y), line, fontname="n", fontsize=22)
            y += 52
    return doc.tobytes()


async def run_lecture(http: httpx.AsyncClient, url: str, lecture: dict, notebook: bool, pace: float = 0.6) -> dict:
    if notebook:
        doc = (await http.post("/documents/notebook", json={"title": lecture["title"]})).raise_for_status().json()
    else:
        files = {"file": (f"{lecture['title']}.pdf", make_pdf(lecture), "application/pdf")}
        doc = (await http.post("/documents", files=files)).raise_for_status().json()
    session = (await http.post("/sessions", json={"document_id": doc["id"]})).raise_for_status().json()
    sid = session["id"]
    counts = {"annotation_added": 0, "term": 0, "task_added": 0, "page_added": 0}

    ws_url = url.replace("http", "ws", 1) + f"/sessions/{sid}/stream"
    async with websockets.connect(ws_url, max_size=None) as ws:
        async def listen():
            async for message in ws:
                kind = json.loads(message).get("type")
                if kind in counts:
                    counts[kind] += 1

        listener = asyncio.create_task(listen())
        await ws.send(json.dumps({"type": "page_view", "page": 1, "initial": True}))
        at = 0
        for s in lecture["speech"]:
            length = max(1500, len(s["text"]) * 180)  # 한 글자에 0.18초쯤
            await ws.send(json.dumps({"type": "transcript_final", "text": s["text"], "start_ms": at, "end_ms": at + length}))
            at += length + 400
            await asyncio.sleep(pace)  # Groq 무료 한도(분당 토큰)를 넘지 않게 천천히
        await ws.send(json.dumps({"type": "flush"}))
        # 마지막 필기가 올 때까지 기다린다 (새 이벤트가 20초 동안 없으면 끝)
        last, idle = sum(counts.values()), 0
        while idle < 20:
            await asyncio.sleep(2)
            now = sum(counts.values())
            idle = 0 if now != last else idle + 2
            last = now
        listener.cancel()

    # 수업 중 기능들도 한 번씩 (학습 데이터에 여러 작업이 고르게 들어가게)
    r = Retrying(http)
    page_no = random.randint(1, max(1, len(lecture["pages"])))
    await r.json("POST", f"/sessions/{sid}/ask", json={"question": random.choice(
        ["방금 뭐라고 했어?", "쉽게 다시 설명해 줘", "예시 하나만 들어 줘", "이거 시험에 어떻게 나올까?"]), "page_no": page_no})
    await r.json("POST", f"/sessions/{sid}/catch-up", json={"minutes": random.choice([1, 3, 5])})
    mark = await r.json("POST", f"/sessions/{sid}/confused", json={"page_no": page_no})
    if mark:
        await r.json("POST", f"/marks/{mark['id']}/explain")

    await r.json("POST", f"/sessions/{sid}/end")
    for _ in range(200):  # 요약·퀴즈
        state = await r.json("GET", f"/sessions/{sid}/summary")
        if not state or state["status"] in ("done", "failed"):
            break
        await asyncio.sleep(3)
    for kind in ("flashcards", "concepts", "mindmap"):
        await r.json("POST", f"/sessions/{sid}/study/{kind}")
        for _ in range(200):
            state = await r.json("GET", f"/sessions/{sid}/study/{kind}")
            if not state or state["status"] != "building":
                break
            await asyncio.sleep(3)
    await r.json("POST", f"/sessions/{sid}/tutor", json={"messages": [{"role": "user", "content": random.choice(
        ["오늘 강의 핵심이 뭐야?", "시험에 나올 만한 거 알려줘", "제일 어려운 개념 쉽게 설명해 줘"])}]})
    if not notebook:
        await r.json("POST", f"/documents/{doc['id']}/exam-questions")
        for _ in range(200):
            state = await r.json("GET", f"/documents/{doc['id']}/exam-map")
            if not state or state["job"]["status"] != "building":
                break
            await asyncio.sleep(3)
    counts["failed"] = r.failed
    return counts


class Retrying:
    """서버가 쉬는 연결을 닫는 순간과 겹치면 ReadError가 나므로 몇 번 다시 보낸다.
    한 단계가 끝내 실패해도 나머지 단계는 계속하고, 실패한 단계 이름을 남긴다."""

    def __init__(self, http: httpx.AsyncClient):
        self.http = http
        self.failed: list[str] = []

    async def json(self, method: str, path: str, **kw):
        name = f"{method} {path.rsplit('/', 1)[-1]}"
        for attempt in range(4):
            try:
                res = await self.http.request(method, path, **kw)
            except (httpx.ReadError, httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout) as exc:
                if attempt == 3:
                    self.failed.append(f"{name} ({type(exc).__name__})")
                    return None
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if res.status_code >= 400:
                self.failed.append(f"{name} ({res.status_code})")
                return None
            return res.json() if res.content else {}
        return None


async def main(url: str, count: int, seed: int | None, pace: float = 0.6) -> None:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise SystemExit("GROQ_API_KEY가 필요합니다 (강의를 만드는 데 씁니다)")
    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    rng = random.Random(seed)
    random.seed(seed)
    picks = [(s, rng.choice(topics)) for s, topics in rng.sample(SUBJECTS, k=min(count, len(SUBJECTS)))]
    while len(picks) < count:
        s, topics = rng.choice(SUBJECTS)
        picks.append((s, rng.choice(topics)))

    async with httpx.AsyncClient(base_url="https://api.groq.com/openai/v1", timeout=180,
                                 headers={"Authorization": f"Bearer {key}"}) as groq, \
               httpx.AsyncClient(base_url=url, timeout=600) as http:
        for i, (subject, topic) in enumerate(picks, start=1):
            started = time.monotonic()
            notebook = i % 3 == 0  # 셋 중 하나는 강의자료 없는 노트 수업
            print(f"[{i}/{count}] {subject} · {topic}{' (노트 수업)' if notebook else ''}", flush=True)
            try:
                lecture = await make_lecture(groq, model, subject, topic, rng.randint(4, 7), rng.randint(24, 40))
                print(f"    슬라이드 {len(lecture['pages'])}장 · 문장 {len(lecture['speech'])}개", flush=True)
                counts = await run_lecture(http, url, lecture, notebook, pace)
                extra = f" · 새 주제 {counts['page_added']}" if notebook else ""
                print(f"    필기 {counts['annotation_added']} · 용어 {counts['term']} · 과제 {counts['task_added']}{extra}"
                      f" · {time.monotonic() - started:.0f}초", flush=True)
                if counts["failed"]:
                    print(f"    못 한 단계: {', '.join(counts['failed'])}", flush=True)
            except Exception as exc:  # 하나가 실패해도 나머지는 계속
                print(f"    실패: {type(exc).__name__}: {exc}", flush=True)
                traceback.print_exc()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--pace", type=float, default=0.6, help="문장 사이 간격(초). 무료 한도에 걸리면 늘린다")
    args = parser.parse_args()
    asyncio.run(main(args.url, args.count, args.seed, args.pace))
