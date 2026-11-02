import asyncio
import json
import os
import subprocess
import tempfile

os.environ.setdefault("LLM_MODE", "fake")

import httpx  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from app import groq  # noqa: E402
from app.groq import GroqLLM, GroqTranscriber  # noqa: E402

@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    # settings는 바꿀 수 없는(frozen) 데이터클래스라 테스트 동안만 직접 넣는다
    monkeypatch.setattr(groq, "settings", groq.settings.__class__(groq_api_key="test-key"))
    monkeypatch.setattr(groq, "_wait_seconds", lambda response, attempt: 0)


def test_chat_sends_schema_retries_rate_limit_and_parses():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(429, headers={"retry-after": "1"}, json={"error": "rate"})
        content = json.dumps({"points": ["경사하강법: 기울기 반대 방향으로 이동"]}, ensure_ascii=False)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    llm = GroqLLM(transport=httpx.MockTransport(handler))
    points = asyncio.run(llm.organize_page({"page_no": 1, "text": "경사하강법"}, "기울기 반대로 가요", []))
    assert points == ["경사하강법: 기울기 반대 방향으로 이동"]
    body = json.loads(seen[-1].content)
    assert seen[-1].headers["authorization"] == "Bearer test-key"
    assert body["response_format"]["json_schema"]["schema"]["required"] == ["points"]
    assert body["reasoning_effort"] == "low"


def test_schema_failure_is_retried_like_bad_json():
    replies = [httpx.Response(400, json={"error": {"code": "json_validate_failed"}}),
               httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
                   {"summary": "경사하강법은 기울기 반대 방향으로 조금씩 이동한다.", "quiz": {}}, ensure_ascii=False)}}]}),
               httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
                   {"overview": "경사하강법을 배웠다. 학습률이 중요하다."}, ensure_ascii=False)}}]})]
    llm = GroqLLM(transport=httpx.MockTransport(lambda request: replies.pop(0)))
    result = asyncio.run(llm.summarize([{"page_no": 1, "text": "경사하강법"}],
                                       [{"page_no": 1, "text": "학습률이 크면 발산해요."}], []))
    assert result["pages"][0]["summary"].startswith("경사하강법은") and result["quiz"] == []


def test_transcribe_file_in_chunks_with_offsets(monkeypatch):
    monkeypatch.setattr(groq, "CHUNK_SECONDS", 2)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"segments": [{"start": 0.5, "end": 1.5, "text": " 학습률이 크면 발산해요. 꼭 기억하세요."}]})

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "lecture.m4a")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                        "-c:a", "aac", path], check=True)
        progress = []
        segments = GroqTranscriber(transport=httpx.MockTransport(handler)).transcribe(path, "경사하강법", progress.append)
    assert len(requests) == 3 and progress[-1] == 1.0
    # 10분 조각마다 시작 시각을 더해 준다 (여기서는 2초 조각)
    assert [s.start_ms for s in segments[::2]] == [500, 2500, 4500]
    assert segments[1].text == "꼭 기억하세요."
    assert b"whisper-large-v3\r\n" in requests[0].content and b"name=\"language\"" in requests[0].content


def test_transcribe_live_chunk_sends_wav():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content)
        return httpx.Response(200, json={"text": "다음 장, 역전파입니다.", "duration": 2.0})

    segments = GroqTranscriber(transport=httpx.MockTransport(handler)).transcribe(np.zeros(32000, np.float32))
    assert segments[0].text == "다음 장, 역전파입니다." and segments[0].end_ms == 2000
    assert b"RIFF" in seen[0]


def test_unpunctuated_transcript_is_split_at_korean_sentence_endings():
    from app.stt import Segment, split_sentences

    text = ("학습률이 너무 크면 최소값을 지나쳐서 발산하고 너무 작으면 학습이 엄청 느려집니다 "
            "이거 중간고사에 꼭 나와요 다음 장 역전파 입니다 결국 연쇄 법칙을 반복해서 쓰는 거예요")
    parts = split_sentences([Segment(0, 10000, text)])
    assert [p.text for p in parts] == [
        "학습률이 너무 크면 최소값을 지나쳐서 발산하고 너무 작으면 학습이 엄청 느려집니다",
        "이거 중간고사에 꼭 나와요", "다음 장 역전파 입니다", "결국 연쇄 법칙을 반복해서 쓰는 거예요"]
    assert parts[0].start_ms == 0 and parts[-1].end_ms == 10000


def test_fix_speech_only_accepts_small_corrections():
    from app.llm import accept_fixed_speech

    original = "그래서 드롭아웃은 학습할 때 유런 일부를 무작위로 꺼버리는 거예요."
    assert accept_fixed_speech(original, original.replace("유런", "뉴런"))
    assert not accept_fixed_speech(original, "드롭아웃은 뉴런 일부를 무작위로 끈다.")  # 다시 쓴 답은 버린다
