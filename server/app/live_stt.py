"""실시간 Whisper 받아쓰기: 웹앱이 보내는 마이크 소리(16kHz 16비트 PCM)를 모았다가,
말이 잠깐 끊기는 곳(또는 최대 10초)에서 끊어 Whisper로 받아쓴다.

브라우저 내장 음성 인식보다 정확하고(테스트 97%), 어느 브라우저에서나 같게 동작한다.
대신 끊어서 받아쓰므로 자막이 몇 초 늦다.
"""

import asyncio
import logging
import wave
from collections.abc import Awaitable, Callable

import numpy as np

from .stt import split_sentences

log = logging.getLogger(__name__)

RATE = 16000
FRAME = 480                 # 30ms
MIN_SPEECH_MS = 1500        # 이보다 짧은 조각은 끊지 않고 더 모은다
SILENCE_TO_CUT_MS = 700     # 이만큼 조용하면 문장이 끝났다고 본다
MAX_CHUNK_MS = 10_000       # 말이 안 끊겨도 이 길이에서는 끊는다
PRE_ROLL = RATE * 3 // 10   # 말 시작 직전 0.3초는 남긴다 (첫 음절이 잘리지 않게)

OnText = Callable[[str, int, int, bool], Awaitable[None]]
LOUD_RATIO = 1.4  # 최근 조각들의 가운데 크기보다 이만큼 크면 목소리를 높인 것


class RecordOnly:
    """폰이 받아쓸 때: 소리는 녹음 파일로만 남기고 받아쓰지 않는다 (조각도 길게 모아 일을 줄인다)."""
    min_chunk_ms = 60_000
    max_chunk_ms = 60_000

    def transcribe(self, audio, hint: str = "", on_progress=None) -> list:
        return []


class LiveAudio:
    def __init__(self, transcriber, hint: str, on_text: OnText, wav_path: str | None = None, start_ms: int = 0):
        self.transcriber = transcriber
        # 받아쓰기 서비스마다 알맞은 조각 길이 (Groq는 길게 모아서 무료 한도를 아낀다, 이 서버의 Whisper는 짧게 바로)
        self.min_chunk_ms = getattr(transcriber, "min_chunk_ms", 0)
        self.max_chunk_ms = getattr(transcriber, "max_chunk_ms", MAX_CHUNK_MS)
        self.hint = hint
        self.on_text = on_text
        self.buffer = np.zeros(0, dtype=np.int16)
        self.buffer_start_ms = start_ms  # 버퍼 첫 샘플의 강의 시각
        self.total_samples = start_ms * RATE // 1000
        self.silent_ms = 0
        self.speech_ms = 0
        self.noise = 300.0            # 배경 소음 크기 추정 (int16 RMS)
        self.last_text = ""
        # 목소리 강조: 조각마다 말소리 평균 크기를 재어, 최근 조각들보다 확 크면 "목소리 높임"으로 본다
        self.speech_energy = 0.0
        self.speech_frames = 0
        self.levels: list[float] = []
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker = asyncio.create_task(self._run())
        # 수업 전체 녹음을 남겨 두면 나중에 다시 정리할 수 있다
        self.wav = None
        if wav_path:
            self.wav = wave.open(wav_path, "wb")
            self.wav.setnchannels(1)
            self.wav.setsampwidth(2)
            self.wav.setframerate(RATE)

    def use(self, transcriber) -> None:
        """받아쓰는 쪽을 바꾼다 (폰 받아쓰기가 준비되면 서버는 녹음만)."""
        self.transcriber = transcriber
        self.min_chunk_ms = getattr(transcriber, "min_chunk_ms", 0)
        self.max_chunk_ms = getattr(transcriber, "max_chunk_ms", MAX_CHUNK_MS)

    def feed(self, data: bytes) -> None:
        samples = np.frombuffer(data[: len(data) // 2 * 2], dtype=np.int16)
        if self.wav:
            self.wav.writeframes(samples.tobytes())
        for i in range(0, len(samples), FRAME):
            frame = samples[i:i + FRAME]
            rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2))) if len(frame) else 0.0
            speaking = rms > max(self.noise * 2.5, 400)
            if not speaking:
                self.noise = 0.95 * self.noise + 0.05 * rms
            ms = len(frame) * 1000 // RATE
            self.speech_ms += ms if speaking else 0
            if speaking:
                self.speech_energy += rms
                self.speech_frames += 1
            self.silent_ms = 0 if speaking else self.silent_ms + ms
            self.buffer = np.concatenate([self.buffer, frame])
            self.total_samples += len(frame)
            length_ms = len(self.buffer) * 1000 // RATE
            if self.speech_ms == 0 and len(self.buffer) > PRE_ROLL:
                # 말이 시작되기 전 침묵은 직전 0.3초만 남기고 버린다 (Whisper가 침묵에서 헛말을 지어내는 것도 막는다)
                drop = len(self.buffer) - PRE_ROLL
                self.buffer = self.buffer[drop:]
                self.buffer_start_ms += drop * 1000 // RATE
            elif (self.speech_ms >= MIN_SPEECH_MS and self.silent_ms >= SILENCE_TO_CUT_MS and length_ms >= self.min_chunk_ms) \
                    or length_ms >= self.max_chunk_ms:
                self._cut()

    def _reset(self) -> None:
        self.buffer = np.zeros(0, dtype=np.int16)
        self.buffer_start_ms = self.total_samples * 1000 // RATE
        self.speech_ms = 0
        self.silent_ms = 0
        self.speech_energy = 0.0
        self.speech_frames = 0

    def _loud(self) -> bool:
        if not self.speech_frames:
            return False
        level = self.speech_energy / self.speech_frames
        history = sorted(self.levels[-30:])
        loud = len(history) >= 5 and level > history[len(history) // 2] * LOUD_RATIO
        self.levels.append(level)
        return loud

    def _cut(self) -> None:
        if self.speech_ms > 0:
            self._queue.put_nowait((self.buffer_start_ms, self.buffer.copy(), self._loud()))
        self._reset()

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            start_ms, pcm, loud = item
            audio = pcm.astype(np.float32) / 32768.0
            prompt = f"{self.hint} {self.last_text}".strip()
            try:
                segments = await asyncio.to_thread(self.transcriber.transcribe, audio, prompt)
            except Exception:
                log.exception("실시간 받아쓰기 실패")
                continue
            for seg in split_sentences(segments):
                self.last_text = seg.text
                await self.on_text(seg.text, start_ms + seg.start_ms, start_ms + seg.end_ms, loud)

    async def close(self) -> None:
        self._cut()
        self._queue.put_nowait(None)
        await self._worker
        if self.wav:
            self.wav.close()
