"""환경변수로 바꿀 수 있는 서버 설정."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str = os.getenv("DB_PATH", "data/lecture_notes.db")
    upload_dir: str = os.getenv("UPLOAD_DIR", "data/uploads")

    # "ollama" = 내 컴퓨터의 무료 공개 모델 (기본값)
    # "claude" = Claude API (유료, 품질 최고)
    # "fake"   = 테스트·화면 개발용 가짜 응답
    llm_mode: str = os.getenv("LLM_MODE", "ollama")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3:8b")

    # 실시간 필기용 모델과 강의 후 요약·퀴즈용 모델
    annotation_model: str = os.getenv("ANNOTATION_MODEL", "claude-opus-5-5")
    annotation_effort: str = os.getenv("ANNOTATION_EFFORT", "low")
    summary_model: str = os.getenv("SUMMARY_MODEL", "claude-opus-5-5")
    summary_effort: str = os.getenv("SUMMARY_EFFORT", "medium")

    # 필기 생성 조건: 새 받아쓰기가 이 글자 수를 넘거나, 이 시간이 지나면 호출
    min_chars_per_call: int = int(os.getenv("MIN_CHARS_PER_CALL", "80"))
    max_wait_seconds: float = float(os.getenv("MAX_WAIT_SECONDS", "8"))

    # 자동 페이지 추정 확신이 이 값보다 낮으면 후보 페이지를 AI에게 보여 주고 고르게 한다
    page_confidence: float = float(os.getenv("PAGE_CONFIDENCE", "0.6"))
    # 강의 후 웹 검색으로 추가 자료 찾기 (1 = 켜기)
    enable_web_tips: bool = os.getenv("ENABLE_WEB_TIPS", "1") == "1"


settings = Settings()
