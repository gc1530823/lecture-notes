import pytest
import os

# 시험 중에는 한국어 글자 인식 모델(약 10MB)을 인터넷에서 받지 않는다
os.environ.setdefault("OCR_DISABLED", "1")


@pytest.fixture(autouse=True)
def _fresh_groq_limits():
    """Groq 모델 한도 기억은 프로세스 전체가 같이 쓴다 → 테스트마다 비운다"""
    from app.groq import GroqLLM
    GroqLLM._cooldown.clear()
    GroqLLM._text_cache = None
    yield
    GroqLLM._cooldown.clear()
    GroqLLM._text_cache = None
