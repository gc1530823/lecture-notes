"""녹음 파일 받아쓰기 (무료): faster-whisper로 서버에서 한국어 음성을 글자로 바꾼다.

iPhone 웹앱은 화면이 꺼지면 받아쓰기가 멈추므로, 수업은 '음성 메모'로 녹음해 두고
끝난 뒤 파일을 올리면 이 모듈이 받아쓴다. 모델은 처음 쓸 때 한 번만 내려받는다.
"""

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass

from .config import settings

log = logging.getLogger(__name__)


@dataclass
class Segment:
    start_ms: int
    end_ms: int
    text: str


def split_sentences(segments: list["Segment"]) -> list["Segment"]:
    """Whisper는 여러 문장을 한 덩어리로 묶곤 한다. "…나와요. 다음 장, 역전파입니다."처럼 페이지가 바뀌는 말이
    한 덩어리에 섞이면 페이지 추적이 틀리므로, 문장으로 나누고 시각은 글자 수 비율로 나눠 준다."""
    result = []
    for seg in segments:
        parts = [p.strip() for p in re.split(r"(?<=[.?!])\s+", seg.text) if p.strip()]
        total = sum(len(p) for p in parts) or 1
        start = seg.start_ms
        for part in parts:
            end = start + round((seg.end_ms - seg.start_ms) * len(part) / total)
            result.append(Segment(start, end, part))
            start = end
    return result


class WhisperTranscriber:
    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel  # 무거운 의존성이라 필요할 때만 불러온다

                log.info("Whisper 모델 준비 중: %s", settings.whisper_model)
                self._model = WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, path: str, hint: str = "", on_progress: Callable[[float], None] | None = None) -> list[Segment]:
        """오래 걸리는 작업이라 스레드에서 부른다. hint에는 강의자료 용어를 넣어 전문용어 인식을 돕는다."""
        model = self._load()
        segments, info = model.transcribe(
            path, language="ko", vad_filter=True, beam_size=1, initial_prompt=hint or None,
        )
        result = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                result.append(Segment(int(seg.start * 1000), int(seg.end * 1000), text))
            if on_progress and info.duration:
                on_progress(min(seg.end / info.duration, 1.0))
        return split_sentences(result)


class FakeTranscriber:
    """화면·흐름 개발용 (STT_MODE=fake): 어떤 파일이든 정해 둔 받아쓰기를 돌려준다."""

    LINES = [
        "자 오늘은 경사하강법부터 볼게요. 산에서 눈을 감고 내려간다고 생각하면 돼요.",
        "학습률이 너무 크면 발산하고 너무 작으면 학습이 느려집니다. 이거 시험에 꼭 나와요.",
        "다음 장, 역전파입니다. 결국 연쇄 법칙을 반복해서 쓰는 거예요.",
        "과제 2번은 역전파를 손으로 계산해 보는 거고 다음 주 금요일까지 제출하세요.",
    ]

    def transcribe(self, path: str, hint: str = "", on_progress: Callable[[float], None] | None = None) -> list[Segment]:
        import time

        result = []
        for i, line in enumerate(self.LINES):
            time.sleep(0.5)
            result.append(Segment(i * 6000, i * 6000 + 5000, line))
            if on_progress:
                on_progress((i + 1) / len(self.LINES))
        return result


def make_transcriber():
    return FakeTranscriber() if settings.stt_mode == "fake" else WhisperTranscriber()
