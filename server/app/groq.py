"""Groq 모드 (무료 사용량 안에서 무료, 빠름): Groq 클라우드에서 Whisper 받아쓰기와 필기·요약 AI를 돌린다.

GROQ_API_KEY만 넣으면 받아쓰기와 AI가 모두 Groq로 바뀐다. 그래픽카드 없는 컴퓨터에서 1~2분 걸리던 필기가
몇 초로, 1시간 녹음 받아쓰기가 1분 안팎으로 줄어든다. 대신 녹음과 받아쓰기가 Groq 서버로 간다.
API는 OpenAI와 같은 형식이고, 프롬프트·스키마와 페이지별로 나눠 요약하는 방식은 무료(Ollama) 모드와 같다.
"""

import asyncio
import contextvars
import io
import json
import re
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
from .llm import BOARD_SYSTEM, TIMETABLE_SYSTEM, FIX_SPEECH_SCHEMA, FIX_SPEECH_SYSTEM, LLMError, _fix_speech_prompt
from .ollama_llm import OllamaLLM
from .stt import PROMPT_LEAD, Segment, foreign_noise, is_hallucination, split_sentences

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

    async def study_note(self, prompt: str) -> dict:
        token = _EFFORT.set("medium")  # 정리 노트는 자료 전체를 이해해야 해서 더 깊이
        try:
            return await super().study_note(prompt)
        finally:
            _EFFORT.reset(token)

    async def quiz_set(self, prompt: str) -> list[dict]:
        token = _EFFORT.set("medium")  # 문제를 내기 전에 자료를 더 깊이 공부하게
        try:
            return await super().quiz_set(prompt)
        finally:
            _EFFORT.reset(token)

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
        # 사용량 한도는 모델마다 따로다: 기본 모델이 차면 기다리기 전에 다른 무료 모델로 (긴 강의를 정리할 때 요약 단계에서 멈추지 않게)
        spare = [m for m in settings.groq_fallback_models if m != settings.groq_model]
        for attempt in range(MAX_RETRIES):
            try:
                response = await self.client.post("/chat/completions", json=payload, headers=_auth())
            except httpx.HTTPError as exc:
                raise LLMError(f"Groq에 연결할 수 없습니다: {exc}") from exc
            if response.status_code == 429 and spare:
                log.warning("Groq %s 한도: %s 로 넘깁니다", payload["model"], spare[0])
                payload["model"] = spare.pop(0)
                continue
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
        training_log.record(system, prompt, schema, data, f"groq:{payload['model']}")
        return data

    async def warm_up(self) -> None:
        return None

    async def read_board(self, image: bytes, mime: str) -> dict:
        """Groq의 사진 읽는 모델(GROQ_VISION_MODEL)로 칠판 사진을 필기로 옮긴다 (무료 사용량)."""
        return await self._vision(BOARD_SYSTEM, "이 사진을 필기로 옮겨 주세요.", image, mime)

    async def read_timetable(self, image: bytes, mime: str) -> dict:
        """시간표 캡처(에브리타임·학교 포털)를 수업 목록으로"""
        return await self._vision(TIMETABLE_SYSTEM, "이 시간표의 수업을 모두 옮겨 주세요.", image, mime)

    async def _vision(self, system: str, ask: str, image: bytes, mime: str) -> dict:
        import base64

        # 사진 읽는 모델은 Groq 에서 자주 바뀌고 없어진다 → 정해 둔 모델이 안 되면 지금 있는 사진 모델을 찾아 차례로 써 본다
        image_url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        problems = []
        for model in await self._vision_models():
            for strict in (True, False):  # JSON 모드를 못 쓰는 모델이면 그냥 글로 받아 JSON 만 골라낸다
                payload = {
                    "model": model,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": [{"type": "text", "text": ask + " JSON 으로만 답해 주세요."},
                                                              {"type": "image_url", "image_url": {"url": image_url}}]}],
                    "temperature": 0.1,
                    **({"response_format": {"type": "json_object"}} if strict else {}),
                }
                try:
                    response = await self.client.post("/chat/completions", json=payload, headers=_auth())
                except httpx.HTTPError as exc:
                    raise LLMError(f"Groq에 연결할 수 없습니다: {exc}") from exc
                if response.status_code < 400:
                    text = response.json()["choices"][0]["message"].get("content") or ""
                    try:
                        return json.loads(text[text.find("{"): text.rfind("}") + 1])
                    except json.JSONDecodeError:
                        problems.append(f"{model}: 답이 JSON 이 아님")
                        continue
                body = response.text[:200]
                problems.append(f"{model}: {response.status_code} {body}")
                log.warning("사진 읽기 실패 %s %s %s", model, response.status_code, body)
                if response.status_code == 429:
                    raise LLMError("Groq 무료 사용량이 잠깐 다 찼어요. 1분쯤 뒤 다시 해 주세요.")
                if not (response.status_code == 400 and strict and ("json" in body.lower() or "response_format" in body)):
                    break  # 이 모델은 안 된다 → 다음 모델
        raise LLMError("사진 읽는 모델을 쓸 수 없어요: " + " / ".join(problems)[:400])

    _vision_cache: list[str] | None = None

    async def _vision_models(self) -> list[str]:
        """정해 둔 사진 모델 + Groq 에 지금 있는 사진 모델들 (이름으로 고른다)"""
        if GroqLLM._vision_cache is None:
            found: list[str] = []
            try:
                response = await self.client.get("/models", headers=_auth())
                ids = [m.get("id", "") for m in response.json().get("data", [])] if response.status_code < 400 else []
                found = [i for i in ids if re.search(r"vision|llama-4|scout|maverick|[-_]vl|pixtral|gemma-3", i, re.I)
                         and not re.search(r"whisper|guard|tts|prompt", i, re.I)]
                found.sort(key=lambda i: (0 if "scout" in i else 1 if "maverick" in i else 2, i))
            except (httpx.HTTPError, ValueError):
                pass
            GroqLLM._vision_cache = found
        return list(dict.fromkeys([settings.groq_vision_model, *GroqLLM._vision_cache]))

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
    r = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-i", path, "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame",
         "-b:a", "32k", "-f", "segment", "-segment_time", str(CHUNK_SECONDS), os.path.join(out_dir, "part%03d.mp3")],
        capture_output=True,
    )
    if r.returncode:   # 왜 실패했는지 남긴다 (-9 = 메모리 부족으로 꺼짐, 'No space' = 디스크 가득)
        why = "메모리 부족으로 꺼짐" if r.returncode in (-9, 137) else (r.stderr or b"").decode(errors="replace").strip()[-200:]
        raise RuntimeError(f"ffmpeg 실패 (코드 {r.returncode}): {why}")
    return sorted(os.path.join(out_dir, n) for n in os.listdir(out_dir) if n.startswith("part"))


def _latin_lines(segments) -> int:
    """한글 없이 로마자만 있는 줄 수 (한국어 강의에서 Whisper 가 영어·로마자로 새어 버린 줄)"""
    return sum(1 for s in segments if not re.search(r"[가-힣]", s.text) and len(re.findall(r"[A-Za-z]", s.text)) >= 5)


# 받아쓰기 모델 한도가 차면 바꿔 쓸 짝 (둘 다 무료, 한도는 따로)
OTHER_WHISPER = {"whisper-large-v3": "whisper-large-v3-turbo", "whisper-large-v3-turbo": "whisper-large-v3"}


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

    def _request(self, filename: str, data: bytes, hint: str, model: str, patient: bool = True,
                 language: str | None = None) -> list[Segment]:
        """patient=False: 한도에 걸리면 기다리지 않고 바로 SpeechLimit을 낸다 (이 서버의 Whisper로 넘기려고).
        language=None: Whisper 가 목소리를 듣고 언어를 고른다 (강의자료가 영어여도 한국어로 말하면 한국어로).
        고른 언어는 self.detected 에 남긴다 (녹음 파일은 첫 조각에서 정한 언어를 끝까지 쓴다)."""
        form = {"model": model, "response_format": "verbose_json", "temperature": "0"}
        if language:
            form["language"] = language
        # Whisper는 프롬프트의 말투를 따라 쓰므로, 마침표가 있는 문장을 앞에 두어 문장 끝에 마침표를 찍게 한다.
        # 프롬프트는 짧아야 해서 용어·직전 문장은 뒤쪽만 남긴다
        form["prompt"] = PROMPT_LEAD[language if language in PROMPT_LEAD else "ko"] + hint[-160:]
        switched = False
        for attempt in range(MAX_RETRIES):
            try:
                response = self.client.post("/audio/transcriptions", data=form, files={"file": (filename, data)},
                                            headers=_auth())
            except httpx.HTTPError as exc:
                raise LLMError(f"Groq에 연결할 수 없습니다: {exc}") from exc
            if response.status_code != 429:
                break
            # 한도는 모델마다 따로다: 기다리거나 느린 서버 Whisper 로 넘기기 전에 다른 무료 받아쓰기 모델로 한 번
            other = OTHER_WHISPER.get(form["model"])
            if other and not switched:
                log.warning("Groq %s 한도: %s 로 받아씁니다", form["model"], other)
                form["model"], switched = other, True
                continue
            wait = _wait_seconds(response, attempt)
            if not patient:
                raise SpeechLimit(f"Groq 받아쓰기 한도 ({wait:.0f}초 뒤 풀림)", wait)
            log.warning("Groq 받아쓰기 사용량 한도: %.0f초 기다립니다", wait)
            time.sleep(wait)
        if response.status_code >= 400:
            detail = " ".join(response.text.split())[:400] or "(내용 없음)"
            log.warning("Groq 받아쓰기 오류 %s: %s (파일 %s, %d바이트, 프롬프트 %d자)", response.status_code, detail, filename,
                        len(data), len(form.get("prompt", "")))
            raise LLMError(f"Groq 받아쓰기 오류 ({response.status_code}): {detail}")
        body = response.json()
        self.detected = {"korean": "ko", "english": "en"}.get(str(body.get("language", "")).lower(), body.get("language") or None)
        segments = body.get("segments") or [{"start": 0, "end": body.get("duration", 0), "text": body.get("text", "")}]
        kept = []
        for s in segments:
            text = s.get("text", "").strip()
            if not text:
                continue
            if foreign_noise(text, language or self.detected):
                log.info("받아쓰기 버림 (한국어 강의에 끼어든 외국어): %r", text[:80])
                continue
            if is_hallucination(text, hint, s.get("no_speech_prob", 0.0), s.get("compression_ratio", 1.0), s.get("avg_logprob")):
                log.info("받아쓰기 버림 (지어낸 말로 봄): %r 없음=%.2f 압축=%.2f 확신=%s", text[:80], s.get("no_speech_prob", 0.0),
                         s.get("compression_ratio", 1.0), s.get("avg_logprob"))
                continue
            kept.append(Segment(int(s["start"] * 1000), int(s["end"] * 1000), text))
        return kept

    def transcribe(self, audio, hint: str = "", on_progress: Callable[[float], None] | None = None,
                   patient: bool = True, language: str | None = None) -> list[Segment]:
        """audio: 파일 경로, 또는 16kHz 모노 float32 배열(실시간 조각). WhisperTranscriber와 같은 꼴로 돌려준다."""
        if not isinstance(audio, str):
            return split_sentences(self._request("live.wav", _wav_bytes(audio), hint, settings.groq_live_whisper_model,
                                                 patient, language))
        result: list[Segment] = []
        # 사람이 '영어 강의'라고 정했으면 그 언어로, 아니면 첫 조각에서 목소리로 정하고 다음 조각부터는 고정
        language = language or None
        with tempfile.TemporaryDirectory() as tmp:
            parts = _split_audio(audio, tmp)
            for i, part in enumerate(parts):
                offset = i * CHUNK_SECONDS * 1000
                with open(part, "rb") as f:
                    data = f.read()
                if len(data) < 4000:  # 끝에 남는 1초 남짓한 조각: 받아쓸 말이 없고 Groq가 거절하기도 한다
                    continue
                try:
                    segments = self._request(os.path.basename(part), data, hint, settings.groq_whisper_model, patient, language)
                    if language is None and getattr(self, "detected", None) not in (None, "ko", "en"):
                        # 첫 조각이 조용하면 엉뚱한 언어(프랑스어 등)로 잡기도 한다 → 한국어로 다시
                        log.warning("받아쓰기 언어를 %s 로 잡음 → 한국어로 다시", self.detected)
                        language = "ko"
                        segments = self._request(os.path.basename(part), data, hint, settings.groq_whisper_model, patient, language)
                    if language is None and segments:
                        language = getattr(self, "detected", None)
                        if language == "ko" and _latin_lines(segments) >= 2:
                            # 첫 조각은 언어를 스스로 정하느라 중간에 영어로 새기도 한다 ("It is a manual…", "JAAKIN")
                            log.warning("첫 조각에 영어로 샌 줄이 있어 한국어로 다시 받아씁니다")
                            segments = self._request(os.path.basename(part), data, hint, settings.groq_whisper_model,
                                                     patient, "ko")
                except SpeechLimit:
                    raise
                except LLMError as exc:
                    if "연결할 수 없" in str(exc):
                        raise
                    # 프롬프트(용어 힌트) 때문에 거절되는 경우가 있어, 힌트 없이 한 번 더
                    log.warning("받아쓰기 조각 %d 다시 시도 (힌트 없이): %s", i, exc)
                    segments = self._request(os.path.basename(part), data, "", settings.groq_whisper_model, patient, language)
                result += [Segment(s.start_ms + offset, s.end_ms + offset, s.text) for s in segments]
                if on_progress:
                    on_progress((i + 1) / len(parts))
        return split_sentences(result)
