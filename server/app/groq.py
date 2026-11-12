"""Groq 모드 (무료 사용량 안에서 무료, 빠름): Groq 클라우드에서 Whisper 받아쓰기와 필기·요약 AI를 돌린다.

GROQ_API_KEY만 넣으면 받아쓰기와 AI가 모두 Groq로 바뀐다. 그래픽카드 없는 컴퓨터에서 1~2분 걸리던 필기가
몇 초로, 1시간 녹음 받아쓰기가 1분 안팎으로 줄어든다. 대신 녹음과 받아쓰기가 Groq 서버로 간다.
API는 OpenAI와 같은 형식이고, 프롬프트·스키마와 페이지별로 나눠 요약하는 방식은 무료(Ollama) 모드와 같다.
"""

import asyncio
import contextvars
import io
import json
import logging
import os
import subprocess
import tempfile
import time
import wave
from collections.abc import Callable

import httpx
import numpy as np

from . import training_log
from .config import settings
from .llm import BOARD_SYSTEM, FIX_SPEECH_SCHEMA, FIX_SPEECH_SYSTEM, LLMError, _fix_speech_prompt
from .ollama_llm import OllamaLLM
from .stt import PROMPT_LEAD, Segment, guess_language, is_hallucination, split_sentences

log = logging.getLogger(__name__)

BASE_URL = "https://api.groq.com/openai/v1"
# 무료 등급은 파일 하나에 25MB까지라, 16kHz 모노 32kbps mp3(1시간 약 14MB)로 바꾼 뒤 10분씩 나눠 보낸다
CHUNK_SECONDS = 600
MAX_RETRIES = int(os.getenv("GROQ_MAX_RETRIES", "6"))  # 데이터 만들기처럼 몰아서 쓸 때는 늘린다


_EFFORT: contextvars.ContextVar[str] = contextvars.ContextVar("groq_effort", default="low")


class GroqLimit(LLMError):
    def __init__(self, message: str, wait: float) -> None:
        super().__init__(message)
        self.wait = wait


def _wait_seconds(response: httpx.Response, attempt: int) -> float:
    """사용량 한도(429)에 걸리면 Groq가 알려 준 만큼(없으면 점점 길게) 기다린다."""
    try:
        return min(float(response.headers.get("retry-after", "")), 60)
    except ValueError:
        return min(2 ** attempt, 30)


def _auth() -> dict:
    if not settings.groq_api_key:
        raise LLMError("GROQ_API_KEY가 없습니다.")
    return {"Authorization": f"Bearer {settings.groq_api_key}"}


class GroqLLM(OllamaLLM):
    max_wait: float | None = None  # 이보다 오래 기다려야 하는 한도면 GroqLimit (None = 끝까지 기다림)

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.client = httpx.AsyncClient(base_url=BASE_URL, timeout=httpx.Timeout(120, connect=10),
                                        transport=transport)

    async def review_notes(self, prompt: str) -> dict:
        token = _EFFORT.set("medium")  # 급하지 않으니 더 깊이 생각하게
        try:
            return await super().review_notes(prompt)
        finally:
            _EFFORT.reset(token)

    async def _chat(self, system: str, prompt: str, schema: dict, context_tokens: int,
                    temperature: float = 0.2) -> dict:
        payload = {
            "model": settings.groq_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "result", "schema": schema}},
            "temperature": temperature,
        }
        if "gpt-oss" in settings.groq_model:
            # 생각을 짧게 해서 실시간 필기를 빠르게 한다 (강의 뒤 필기 다시 확인은 더 깊이 생각하게)
            payload["reasoning_effort"] = _EFFORT.get()
        for attempt in range(MAX_RETRIES):
            try:
                response = await self.client.post("/chat/completions", json=payload, headers=_auth())
            except httpx.HTTPError as exc:
                raise LLMError(f"Groq에 연결할 수 없습니다: {exc}") from exc
            if response.status_code == 429:
                wait = _wait_seconds(response, attempt)
                if self.max_wait is not None and wait > self.max_wait:
                    # 역할 나누기(hybrid): 오래 기다려야 하는 한도(하루 한도 등)면 기다리지 않고 우리 AI에게 넘긴다
                    raise GroqLimit(f"Groq 사용량 한도 ({wait:.0f}초 뒤 풀림)", wait)
                log.warning("Groq 사용량 한도: %.0f초 기다립니다", wait)
                await asyncio.sleep(wait)
                continue
            break
        if response.status_code == 401:
            raise LLMError("GROQ_API_KEY가 올바르지 않습니다.")
        if response.status_code == 400 and "json_validate_failed" in response.text:
            # 모델이 스키마에 안 맞게 답함: 다시 받을 수 있도록 JSON 오류로 알린다
            raise json.JSONDecodeError("Groq 답이 스키마와 맞지 않습니다", response.text[:200], 0)
        if response.status_code >= 400:
            raise LLMError(f"Groq 오류 ({response.status_code}): {response.text[:200]}")
        content = response.json()["choices"][0]["message"].get("content") or ""
        if not content:
            raise LLMError("Groq 응답이 비어 있습니다.")
        data = json.loads(content)
        training_log.record(system, prompt, schema, data, f"groq:{settings.groq_model}")
        return data

    async def warm_up(self) -> None:
        return None

    async def read_board(self, image: bytes, mime: str) -> dict:
        """Groq의 사진 읽는 모델(GROQ_VISION_MODEL)로 칠판 사진을 필기로 옮긴다 (무료 사용량)."""
        import base64

        payload = {
            "model": settings.groq_vision_model,
            "messages": [{"role": "system", "content": BOARD_SYSTEM},
                         {"role": "user", "content": [
                             {"type": "text", "text": "이 사진을 필기로 옮겨 주세요."},
                             {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(image).decode()}"}}]}],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
        try:
            response = await self.client.post("/chat/completions", json=payload, headers=_auth())
        except httpx.HTTPError as exc:
            raise LLMError(f"Groq에 연결할 수 없습니다: {exc}") from exc
        if response.status_code >= 400:
            raise LLMError(f"사진을 읽지 못했습니다 ({response.status_code}): {response.text[:150]}")
        return json.loads(response.json()["choices"][0]["message"].get("content") or "{}")

    async def fix_speech(self, page: dict, speech: str) -> str:
        """정리 PDF의 '교수님 설명'에서 잘못 들린 단어만 고친다 (Groq는 빨라서 페이지마다 한 번 더 불러도 된다)."""
        data = await self._chat(FIX_SPEECH_SYSTEM, _fix_speech_prompt(page, speech), FIX_SPEECH_SCHEMA, 8192, 0)
        return str(data.get("speech", ""))


def _wav_bytes(audio: np.ndarray) -> bytes:
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _split_audio(path: str, out_dir: str) -> list[str]:
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-i", path, "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame",
         "-b:a", "32k", "-f", "segment", "-segment_time", str(CHUNK_SECONDS), os.path.join(out_dir, "part%03d.mp3")],
        check=True,
    )
    return sorted(os.path.join(out_dir, n) for n in os.listdir(out_dir) if n.startswith("part"))


class SpeechLimit(LLMError):
    def __init__(self, message: str, wait: float) -> None:
        super().__init__(message)
        self.wait = wait


class GroqTranscriber:
    # 실시간 조각 길이: Groq 무료는 요청 하나를 짧아도 10초로 세고(시간당 7200초 · 하루 2000번 · 분당 20번),
    # 0.7초 쉼마다 끊으면 75분 수업이 1000번 넘게 나가 한 시간 한도를 넘는다. 9초 넘게 모은 뒤 쉼에서 끊으면
    # 한 시간 강의가 약 300~400번 · 3600초 안쪽 → 하루 5시간쯤까지. 대신 글이 몇 초 늦게 뜬다.
    min_chunk_ms = int(os.getenv("GROQ_LIVE_MIN_CHUNK_MS", "9000"))
    max_chunk_ms = int(os.getenv("GROQ_LIVE_MAX_CHUNK_MS", "20000"))

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(base_url=BASE_URL, timeout=httpx.Timeout(300, connect=10), transport=transport)

    def _request(self, filename: str, data: bytes, hint: str, model: str, patient: bool = True) -> list[Segment]:
        """patient=False: 한도에 걸리면 기다리지 않고 바로 SpeechLimit을 낸다 (이 서버의 Whisper로 넘기려고)."""
        language = guess_language(hint)
        form = {"model": model, "language": language, "response_format": "verbose_json",
                "temperature": "0"}
        # Whisper는 프롬프트의 말투를 따라 쓰므로, 마침표가 있는 문장을 앞에 두어 문장 끝에 마침표를 찍게 한다.
        # 프롬프트는 짧아야 해서 용어·직전 문장은 뒤쪽만 남긴다
        form["prompt"] = PROMPT_LEAD[language] + hint[-160:]
        for attempt in range(MAX_RETRIES):
            try:
                response = self.client.post("/audio/transcriptions", data=form, files={"file": (filename, data)},
                                            headers=_auth())
            except httpx.HTTPError as exc:
                raise LLMError(f"Groq에 연결할 수 없습니다: {exc}") from exc
            if response.status_code != 429:
                break
            wait = _wait_seconds(response, attempt)
            if not patient:
                raise SpeechLimit(f"Groq 받아쓰기 한도 ({wait:.0f}초 뒤 풀림)", wait)
            log.warning("Groq 받아쓰기 사용량 한도: %.0f초 기다립니다", wait)
            time.sleep(wait)
        if response.status_code >= 400:
            raise LLMError(f"Groq 받아쓰기 오류 ({response.status_code}): {response.text[:200]}")
        body = response.json()
        segments = body.get("segments") or [{"start": 0, "end": body.get("duration", 0), "text": body.get("text", "")}]
        kept = []
        for s in segments:
            text = s.get("text", "").strip()
            if not text:
                continue
            if is_hallucination(text, hint, s.get("no_speech_prob", 0.0), s.get("compression_ratio", 1.0), s.get("avg_logprob")):
                log.info("받아쓰기 버림 (지어낸 말로 봄): %r 없음=%.2f 압축=%.2f 확신=%s", text[:80], s.get("no_speech_prob", 0.0),
                         s.get("compression_ratio", 1.0), s.get("avg_logprob"))
                continue
            kept.append(Segment(int(s["start"] * 1000), int(s["end"] * 1000), text))
        return kept

    def transcribe(self, audio, hint: str = "", on_progress: Callable[[float], None] | None = None,
                   patient: bool = True) -> list[Segment]:
        """audio: 파일 경로, 또는 16kHz 모노 float32 배열(실시간 조각). WhisperTranscriber와 같은 꼴로 돌려준다."""
        if not isinstance(audio, str):
            return split_sentences(self._request("live.wav", _wav_bytes(audio), hint, settings.groq_live_whisper_model,
                                                 patient))
        result: list[Segment] = []
        with tempfile.TemporaryDirectory() as tmp:
            parts = _split_audio(audio, tmp)
            for i, part in enumerate(parts):
                offset = i * CHUNK_SECONDS * 1000
                with open(part, "rb") as f:
                    segments = self._request(os.path.basename(part), f.read(), hint, settings.groq_whisper_model, patient)
                result += [Segment(s.start_ms + offset, s.end_ms + offset, s.text) for s in segments]
                if on_progress:
                    on_progress((i + 1) / len(parts))
        return split_sentences(result)
