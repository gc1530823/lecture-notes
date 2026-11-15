"""녹음 파일 받아쓰기 (무료): faster-whisper로 서버에서 한국어 음성을 글자로 바꾼다.

iPhone 웹앱은 화면이 꺼지면 받아쓰기가 멈추므로, 수업은 '음성 메모'로 녹음해 두고
끝난 뒤 파일을 올리면 이 모듈이 받아쓴다. 모델은 처음 쓸 때 한 번만 내려받는다.
"""

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .config import settings

log = logging.getLogger(__name__)


@dataclass
class Segment:
    start_ms: int
    end_ms: int
    text: str


def guess_language(hint: str) -> str:
    """강의자료 용어(hint)가 대부분 영어면 영어 강의로 본다. Whisper에 언어를 틀리게 주면 정확도가 크게 떨어진다."""
    letters = [c for c in hint if c.isalpha()]
    if len(letters) < 20:
        return "ko"
    latin = sum(1 for c in letters if c.isascii())
    return "en" if latin / len(letters) >= 0.7 else "ko"


PROMPT_LEAD = {"ko": "네, 오늘 수업을 시작하겠습니다. ", "en": "Okay, let's get started today. "}


def is_hallucination(text: str, hint: str, no_speech: float = 0.0, compression: float = 1.0,
                     avg_logprob: float | None = None) -> bool:
    """Whisper가 말이 없는 곳(도입 음악·침묵)에서 지어낸 말:
    말소리가 없을 확률이 높으면서 자신도 없거나, 같은 말이 되풀이되거나(압축률이 높음), 우리가 건넨 용어 힌트를 그대로 읊은 것.
    말소리 없음 확률만으로는 버리지 않는다: Groq Whisper는 진짜 강의 말에도 이 값을 높게 주곤 해서
    공개 강의 테스트에서 15분 중 1분 넘게 말이 통째로 빠졌다 (Whisper 원래 규칙도 '없음 확률 > 0.6 그리고 평균 확신 < -1').
    확신 값이 없는 옛 응답만 없음 확률 하나로 판단한다."""
    if compression >= 2.4 or "♪" in text:
        return True
    if no_speech >= 0.6 and (avg_logprob is None or avg_logprob < -1.0):
        return True
    words = re.findall(r"[A-Za-z가-힣]{2,}", text.lower())
    hint_words = set(re.findall(r"[A-Za-z가-힣]{2,}", hint.lower()))
    if len(words) >= 4 and hint_words and sum(w in hint_words for w in words) / len(words) >= 0.8:
        return True
    if CREDITS.search(text):
        return True
    return text.strip().lower() in {"you", "thank you.", "thanks for watching!", "시청해 주셔서 감사합니다."}


# Whisper 가 조용한 곳에서 지어내는 자막 제작 문구
CREDITS = re.compile(r"amara\.org|captioning|subtitles? by|자막 (제공|제작)|시청해 주셔서|구독과 좋아요|MBC 뉴스", re.I)
# 한국어 강의에 끼어든 유럽 말 (악센트 글자나 흔한 낱말이 있고 한글이 없는 문장). SQL·영어 낱말은 그대로 둔다
EUROPEAN = re.compile(r"[À-ÖØ-öø-ÿ]|\b(le|la|les|des|est|une|que|nous|pour|und|der|die|das|ist|el|los|las|por|para|una)\b", re.I)


def foreign_noise(text: str, language: str | None) -> bool:
    """한국어 강의(language='ko')에서 한글 없이 유럽 말로 된 문장은 Whisper 가 지어낸 것으로 본다"""
    return language == "ko" and not re.search(r"[가-힣]", text) and len(EUROPEAN.findall(text)) >= 2


def split_sentences(segments: list["Segment"]) -> list["Segment"]:
    """Whisper는 여러 문장을 한 덩어리로 묶곤 한다. "…나와요. 다음 장, 역전파입니다."처럼 페이지가 바뀌는 말이
    한 덩어리에 섞이면 페이지 추적이 틀리므로, 문장으로 나누고 시각은 글자 수 비율로 나눠 준다."""
    result = []
    for seg in segments:
        # 마침표를 안 찍는 받아쓰기(Groq 등)는 한국어 문장 끝 말투(~요, ~다, ~죠, ~까) 뒤에서 나눈다
        pattern = r"(?<=[.?!])\s+" if re.search(r"[.?!]", seg.text) else r"(?<=[요다죠까])\s+"
        parts = [p.strip() for p in re.split(pattern, seg.text) if p.strip()]
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

    def transcribe(self, audio, hint: str = "", on_progress: Callable[[float], None] | None = None,
                   language: str | None = None) -> list[Segment]:
        """audio: 파일 경로, 또는 16kHz 모노 float32 배열(실시간 조각).
        오래 걸리는 작업이라 스레드에서 부른다. hint에는 강의자료 용어와 직전 문장을 넣어 인식을 돕는다."""
        model = self._load()
        segments, info = model.transcribe(
            # 서버 CPU 에서는 beam 5 가 2~3배 느리다 → 1 (VAD 로 조용한 곳은 건너뛴다)
            # 언어는 강의자료 글이 아니라 목소리로 정한다 (영어 슬라이드 + 한국어 강의가 흔하다)
            audio, language=language or None, vad_filter=True, beam_size=1, initial_prompt=hint or None,
        )
        result = []
        for seg in segments:
            text = seg.text.strip()
            if text and not is_hallucination(text, hint, seg.no_speech_prob, seg.compression_ratio, seg.avg_logprob):
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

    def transcribe(self, audio, hint: str = "", on_progress: Callable[[float], None] | None = None,
                   language: str | None = None) -> list[Segment]:
        import time

        if not isinstance(audio, str):  # 실시간 조각: 한 문장씩 차례로
            self._next = getattr(self, "_next", -1) + 1
            return [Segment(0, len(audio) * 1000 // 16000, self.LINES[self._next % len(self.LINES)])]
        result = []
        for i, line in enumerate(self.LINES):
            time.sleep(0.5)
            result.append(Segment(i * 6000, i * 6000 + 5000, line))
            if on_progress:
                on_progress((i + 1) / len(self.LINES))
        return result


class FallbackTranscriber:
    """한도 없는 받아쓰기 (STT_MODE=hybrid, Groq 키가 있을 때 기본):
    평소에는 빠르고 정확한 Groq, Groq 무료 한도에 걸리면 기다리지 않고 이 서버의 Whisper(공개 모델, 한도 없음)로 바로 넘어가
    한도가 풀릴 때까지 그쪽으로 받아쓴다. 그래서 긴 수업도, 하루에 여러 수업도 끊기지 않는다."""

    def __init__(self, primary, local) -> None:
        self.primary = primary
        self.local = local
        self.min_chunk_ms = getattr(primary, "min_chunk_ms", 0)
        self.max_chunk_ms = getattr(primary, "max_chunk_ms", 10_000)
        self.local_until = 0.0
        self.local_used = 0  # 몇 번 넘겼는지 (상태 표시·시험용)
        self.last_error = ""  # Groq 가 왜 안 됐는지 (진단용)

    @property
    def engine(self) -> str:
        """지금 받아쓰는 곳: groq(빠름) | local(이 서버, 느림)"""
        return "local" if time.monotonic() < self.local_until else "groq"

    def transcribe(self, audio, hint: str = "", on_progress: Callable[[float], None] | None = None,
                   language: str | None = None) -> list[Segment]:
        from .llm import LLMError

        if time.monotonic() >= self.local_until:
            try:
                return self.primary.transcribe(audio, hint, on_progress, patient=False, **({"language": language} if language else {}))
            except LLMError as exc:
                wait = getattr(exc, "wait", None)
                if wait is not None or "연결할 수 없" in str(exc):
                    # 한도는 보통 몇 분~한 시간 뒤 풀린다. 그동안 매 조각 Groq에 물어보지 않는다
                    self.local_until = time.monotonic() + min(max(wait or 60.0, 30.0), 3600.0)
                # 그 밖의 오류(파일을 거절 등)도 강의를 버리지 않고 이번 것만 이 서버의 Whisper로
                self.last_error = str(exc)[:300]
                log.warning("받아쓰기: %s → 이 서버의 Whisper로 받아씁니다", exc)
        self.local_used += 1
        return self.local.transcribe(audio, hint, on_progress, **({"language": language} if language else {}))


def make_transcriber():
    if settings.stt_mode == "fake":
        return FakeTranscriber()
    if settings.stt_mode == "hybrid":
        from .groq import GroqTranscriber

        return FallbackTranscriber(GroqTranscriber(), WhisperTranscriber())
    if settings.stt_mode == "groq":
        from .groq import GroqTranscriber

        return GroqTranscriber()
    return WhisperTranscriber()
