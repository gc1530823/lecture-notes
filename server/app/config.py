"""환경변수로 바꿀 수 있는 서버 설정."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str = os.getenv("DB_PATH", "data/lecture_notes.db")
    # 우리 AI 만들기: 1이면 AI에 보낸 요청과 답을 학습 데이터로 남긴다 (서버 안에만 저장, app/training_log.py)
    training_log: bool = os.getenv("TRAINING_LOG", "0") == "1"
    training_dir: str = os.getenv("TRAINING_DIR", "data/training")
    upload_dir: str = os.getenv("UPLOAD_DIR", "data/uploads")

    # "groq"   = Groq 클라우드 (무료 사용량 안에서 무료, 빠름). GROQ_API_KEY가 있으면 기본값
    # "ollama" = 내 컴퓨터의 무료 공개 모델 (키가 없을 때 기본값)
    # "claude" = Claude API (유료, 품질 최고)
    # "fake"   = 테스트·화면 개발용 가짜 응답
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    llm_mode: str = os.getenv("LLM_MODE", "groq" if os.getenv("GROQ_API_KEY") else "ollama")
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    # 녹음 파일은 조금 느려도 더 정확한 large-v3, 실시간 조각은 빠른 turbo
    groq_whisper_model: str = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")
    groq_live_whisper_model: str = os.getenv("GROQ_LIVE_WHISPER_MODEL", "whisper-large-v3-turbo")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3:8b")
    # 칠판 사진을 읽는 모델 (사진 입력이 되는 모델)
    groq_vision_model: str = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    ollama_vision_model: str = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:3b")

    # 실시간 필기용 모델과 강의 후 요약·퀴즈용 모델
    annotation_model: str = os.getenv("ANNOTATION_MODEL", "claude-opus-5-5")
    annotation_effort: str = os.getenv("ANNOTATION_EFFORT", "low")
    summary_model: str = os.getenv("SUMMARY_MODEL", "claude-opus-5-5")
    summary_effort: str = os.getenv("SUMMARY_EFFORT", "medium")

    # 필기 생성 조건: 새 받아쓰기가 이 글자 수를 넘거나, 이 시간이 지나면 호출
    min_chars_per_call: int = int(os.getenv("MIN_CHARS_PER_CALL", "80"))
    max_wait_seconds: float = float(os.getenv("MAX_WAIT_SECONDS", "8"))

    # 녹음 파일 받아쓰기 모델 (tiny < base < small < medium: 클수록 정확하지만 느리다)
    whisper_model: str = os.getenv("WHISPER_MODEL", "small")
    # "groq" = Groq의 Whisper large-v3-turbo (GROQ_API_KEY가 있으면 기본값)
    # "whisper" = 이 서버에서 돌리는 faster-whisper, "fake" = 화면 개발용 가짜 받아쓰기
    # "hybrid" = Groq, 한도에 걸리면 이 서버의 Whisper로 (Groq 키가 있을 때 기본 — 한도 없이)
    stt_mode: str = os.getenv("STT_MODE", "hybrid" if os.getenv("GROQ_API_KEY") else "whisper")

    # 자동 페이지 추정 확신이 이 값보다 낮으면 후보 페이지를 AI에게 보여 주고 고르게 한다
    page_confidence: float = float(os.getenv("PAGE_CONFIDENCE", "0.6"))
    # 강의 후 웹 검색으로 추가 자료 찾기 (1 = 켜기)
    enable_web_tips: bool = os.getenv("ENABLE_WEB_TIPS", "1") == "1"


settings = Settings()
