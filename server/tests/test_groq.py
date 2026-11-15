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
                   {"overview": "경사하강법을 배웠다. 학습률이 중요하다."}, ensure_ascii=False)}}]}),
               httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"quiz": []})}}]}),
               httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"quiz": []})}}]})]
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
    # 언어는 목소리로: 첫 조각에는 언어를 정해 보내지 않는다 (강의자료가 영어여도 한국어 강의일 수 있다)
    assert b"whisper-large-v3\r\n" in requests[0].content and b"name=\"language\"" not in requests[0].content


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


def test_study_tools_work_with_groq_page_material(tmp_path, monkeypatch):
    """Groq·Ollama 모드에서 플래시카드·개념을 만들 때 쪽 자료(slide)를 프롬프트가 읽는 모양(text)으로 넘긴다."""
    import asyncio
    import httpx
    from app.groq import GroqLLM
    from app.llm import _organize_prompt

    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["messages"][1]["content"])
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
            {"cards": [{"front": "경사하강법이란?", "back": "기울기 반대로 이동"}]}, ensure_ascii=False)}}]})

    llm = GroqLLM(transport=httpx.MockTransport(handler))
    page = {"page_no": 1, "title": "경사하강법", "slide": "경사하강법 슬라이드", "speech": "설명", "notes": []}
    cards = asyncio.run(llm.study_page("flashcards", {**page, "text": page["slide"]}, page["speech"], page["notes"]))
    assert cards[0]["front"] == "경사하강법이란?" and "경사하강법 슬라이드" in seen[0]
    assert "경사하강법 슬라이드" in _organize_prompt({**page, "text": page["slide"]}, "", [])


def test_english_lecture_is_transcribed_as_english_and_prompt_echo_is_dropped():
    from app.stt import is_hallucination

    hint = "BISECTION string start abcdefgh loop iterates expressions values objects algorithms"
    seen = []

    def handler(request):
        seen.append(request.content)
        return httpx.Response(200, json={"language": "english", "segments": [
            {"start": 0, "end": 20, "text": "BISECTION string start abcdefgh loop", "no_speech_prob": 0.1, "compression_ratio": 1.2},
            {"start": 20, "end": 21, "text": "you", "no_speech_prob": 0.2},
            {"start": 21, "end": 30, "text": "♪ music ♪", "no_speech_prob": 0.9},
            {"start": 30, "end": 35, "text": "Let's dive right in.", "no_speech_prob": 0.01, "compression_ratio": 1.1},
            # 진짜 말인데 없음 확률만 높은 경우 (공개 강의에서 1분이 통째로 빠졌던 것): 확신이 높으면 남긴다
            {"start": 35, "end": 40, "text": "So why do we have multicore processors?", "no_speech_prob": 0.8, "avg_logprob": -0.2},
            {"start": 40, "end": 45, "text": "Subtitles by the community", "no_speech_prob": 0.8, "avg_logprob": -1.4},
        ]})

    t = GroqTranscriber(transport=httpx.MockTransport(handler))
    segments = t._request("a.wav", b"RIFF", hint, "whisper-large-v3")
    assert [s.text for s in segments] == ["Let's dive right in.", "So why do we have multicore processors?"]
    assert b'name="language"' not in seen[0] and t.detected == "en"   # 목소리로 영어라고 알아냄
    t._request("b.wav", b"RIFF", hint, "whisper-large-v3", language="en")
    assert b'name="language"\r\n\r\nen' in seen[1] and b"Okay, let's get started" in seen[1]
    assert not is_hallucination("자 오늘은 경사하강법부터 볼게요", "경사하강법 학습률")


def test_speech_falls_back_to_local_whisper_when_groq_limit_hits_and_comes_back_later(monkeypatch):
    """한도 없는 받아쓰기: Groq가 429면 기다리지 않고 이 서버의 Whisper로, 한도가 풀리면 다시 Groq로."""
    import numpy as np

    from app import stt
    from app.groq import GroqTranscriber

    limited = {"on": True}

    def handler(request):
        if limited["on"]:
            return httpx.Response(429, headers={"retry-after": "40"}, json={"error": {"message": "rate limit"}})
        return httpx.Response(200, json={"segments": [{"start": 0, "end": 2, "text": "그록이 받아쓴 말이에요.", "no_speech_prob": 0.0}]})

    class Local:
        def transcribe(self, audio, hint="", on_progress=None):
            return [stt.Segment(0, 2000, "이 서버가 받아쓴 말이에요.")]

    clock = {"t": 1000.0}
    monkeypatch.setattr(stt.time, "monotonic", lambda: clock["t"])
    t = stt.FallbackTranscriber(GroqTranscriber(transport=httpx.MockTransport(handler)), Local())
    pcm = np.zeros(16000, dtype=np.float32)
    assert t.min_chunk_ms == 9000
    assert [s.text for s in t.transcribe(pcm, "경사하강법")] == ["이 서버가 받아쓴 말이에요."]
    limited["on"] = False
    clock["t"] += 10   # 아직 한도 시간 안: Groq에 묻지도 않는다
    assert [s.text for s in t.transcribe(pcm, "경사하강법")] == ["이 서버가 받아쓴 말이에요."]
    clock["t"] += 60   # 한도가 풀린 뒤에는 다시 Groq
    assert [s.text for s in t.transcribe(pcm, "경사하강법")] == ["그록이 받아쓴 말이에요."]
    assert t.local_used == 2


def test_groq_rejecting_a_file_retries_without_hint_then_falls_back_to_local(tmp_path):
    """Groq가 파일을 400으로 거절해도 강의를 버리지 않는다: 힌트 없이 한 번 더, 그래도 안 되면 이 서버의 Whisper로"""
    import subprocess

    from app import stt
    from app.groq import GroqTranscriber

    audio = tmp_path / "lecture.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-ar", "16000", str(audio)], check=True)
    calls = []

    def handler(request):
        calls.append(b'name="prompt"\r\n\r\n' in request.content and "경사하강법".encode() in request.content)
        if len(calls) == 1:
            return httpx.Response(400, text="")
        return httpx.Response(200, json={"segments": [{"start": 0, "end": 2, "text": "힌트 없이 받아쓴 말이에요.", "no_speech_prob": 0.0}]})

    t = GroqTranscriber(transport=httpx.MockTransport(handler))
    assert [s.text for s in t.transcribe(str(audio), "경사하강법 학습률")] == ["힌트 없이 받아쓴 말이에요."]
    assert calls == [True, False]   # 첫 번째는 힌트와 함께, 다시 할 때는 힌트 없이

    class Local:
        def transcribe(self, audio, hint="", on_progress=None):
            return [stt.Segment(0, 2000, "이 서버가 받아쓴 말이에요.")]

    always_bad = GroqTranscriber(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"error": {"message": "invalid file"}})))
    t2 = stt.FallbackTranscriber(always_bad, Local())
    assert [s.text for s in t2.transcribe(str(audio), "경사하강법")] == ["이 서버가 받아쓴 말이에요."]


def test_speech_switches_to_the_other_free_whisper_model_before_waiting():
    """받아쓰기 한도는 모델마다 따로: 한 모델이 429면 기다리지 않고 다른 무료 모델로 받아쓴다"""
    import numpy as np

    from app.groq import GroqTranscriber

    asked = []

    def handler(request):
        model = next(part for part in request.content.split(b"\r\n") if part.startswith(b"whisper"))
        asked.append(model.decode())
        if model == b"whisper-large-v3-turbo":
            return httpx.Response(429, headers={"retry-after": "40"}, json={"error": {"message": "rate limit"}})
        return httpx.Response(200, json={"segments": [{"start": 0, "end": 2, "text": "다른 모델이 받아썼어요.", "no_speech_prob": 0.0}]})

    t = GroqTranscriber(transport=httpx.MockTransport(handler))
    out = t.transcribe(np.zeros(16000, dtype=np.float32), "", patient=False)
    assert [s.text for s in out] == ["다른 모델이 받아썼어요."]
    assert asked == ["whisper-large-v3-turbo", "whisper-large-v3"]


def test_foreign_noise_and_credits_are_dropped_from_korean_lectures():
    from app.stt import foreign_noise, is_hallucination
    assert foreign_noise("Le premier outil que nous allons utiliser est le outil de soncatch.", "ko")
    assert foreign_noise("Les numéros sont connectés et les numéros sont sélectionnés.", "ko")
    assert not foreign_noise("SELECT name FROM student WHERE age > 20", "ko")     # SQL 은 그대로
    assert not foreign_noise("hello sql 나오는데", "ko")
    assert not foreign_noise("Le premier outil que nous allons utiliser", "fr")  # 프랑스어 강의면 그대로
    assert is_hallucination("〔Captioning provided by the Amara.org community", "")


def test_text_model_switches_to_spare_free_model_on_rate_limit(api_key):
    """글 AI 한도도 모델마다 따로: 기본 모델이 429 면 기다리지 않고 다른 무료 모델로 (긴 강의 요약이 멈추지 않게)"""
    import asyncio
    import json as _json

    from app.groq import GroqLLM
    asked = []

    def handler(request):
        body = _json.loads(request.content)
        asked.append(body["model"])
        if body["model"] == "openai/gpt-oss-120b":
            return httpx.Response(429, headers={"retry-after": "40"}, json={"error": {"message": "rate limit"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"title": "날짜 함수"}'}}]})

    llm = GroqLLM(transport=httpx.MockTransport(handler))
    out = asyncio.run(llm._chat("s", "p", {"type": "object"}, 1024))
    assert out == {"title": "날짜 함수"} and asked == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


def test_first_chunk_leaking_into_english_is_redone_in_korean(monkeypatch, tmp_path):
    """첫 조각은 언어를 스스로 정하다 중간에 영어·로마자로 샌다 → 한국어로 잡히면 그 조각을 한국어로 다시"""
    from app import groq as g

    part = tmp_path / "part000.mp3"
    part.write_bytes(b"x" * 5000)
    monkeypatch.setattr(g, "_split_audio", lambda path, out: [str(part)])
    seen = []

    def handler(request):
        korean = b'name="language"\r\n\r\nko' in request.content
        seen.append(korean)
        if korean:
            return httpx.Response(200, json={"language": "korean", "segments": [
                {"start": 0, "end": 5, "text": "LENGTH 는 바이트 수를 돌려줘요.", "no_speech_prob": 0.0},
                {"start": 5, "end": 9, "text": "CHAR_LENGTH 는 글자 수예요.", "no_speech_prob": 0.0}]})
        return httpx.Response(200, json={"language": "korean", "segments": [
            {"start": 0, "end": 5, "text": "LENGTH 는 바이트 수를 돌려줘요.", "no_speech_prob": 0.0},
            {"start": 5, "end": 7, "text": "It is a manual that I have not used before", "no_speech_prob": 0.0},
            {"start": 7, "end": 9, "text": "NOVAN CONVALIDEMKCHO", "no_speech_prob": 0.0}]})

    t = g.GroqTranscriber(transport=httpx.MockTransport(handler))
    out = t.transcribe("lecture.m4a")
    assert seen == [False, True] and all("manual" not in s.text for s in out)
    assert g._latin_lines([g.Segment(0, 1, "SELECT 문으로 조회해요"), g.Segment(0, 1, "JAAKIN")]) == 1
