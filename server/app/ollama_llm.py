"""무료 모드: 내 컴퓨터에서 도는 Ollama의 공개 모델(Qwen, Gemma 등)로 필기·요약·퀴즈를 만든다.

Ollama의 /api/chat에 JSON 스키마를 format으로 넘기면 그 형식대로 답한다.
프롬프트와 스키마는 Claude 모드와 같은 것을 쓴다.
"""

import json
import logging

import httpx

from .config import settings
from .llm import (
    ANNOTATION_SCHEMA,
    ANNOTATION_SYSTEM,
    SUMMARY_SCHEMA,
    SUMMARY_SYSTEM,
    LLMError,
    _annotation_prompt,
    _summary_prompt,
)

log = logging.getLogger(__name__)


class OllamaLLM:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # 작은 컴퓨터에서는 답이 느릴 수 있어 넉넉하게 기다린다
        self.client = httpx.AsyncClient(base_url=settings.ollama_url, timeout=httpx.Timeout(600, connect=5),
                                        transport=transport)

    async def _chat(self, system: str, prompt: str, schema: dict, context_tokens: int) -> dict:
        payload = {
            "model": settings.ollama_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "format": schema,
            "stream": False,
            # 생각 모드가 있는 모델(Qwen3 등)도 바로 답하게 해서 실시간 필기를 빠르게 한다
            "think": False,
            "keep_alive": "30m",
            "options": {"temperature": 0.2, "num_ctx": context_tokens},
        }
        try:
            response = await self.client.post("/api/chat", json=payload)
        except httpx.ConnectError as exc:
            raise LLMError(f"Ollama에 연결할 수 없습니다 ({settings.ollama_url}). Ollama 앱이 켜져 있는지 확인해 주세요.") from exc
        except httpx.TimeoutException as exc:
            raise LLMError("Ollama 응답이 너무 오래 걸립니다. 더 작은 모델을 써 보세요.") from exc
        if response.status_code == 404:
            raise LLMError(f"모델 {settings.ollama_model}이 없습니다. `ollama pull {settings.ollama_model}`을 먼저 실행해 주세요.")
        if response.status_code >= 400:
            raise LLMError(f"Ollama 오류 ({response.status_code}): {response.text[:200]}")
        content = response.json().get("message", {}).get("content", "")
        if not content:
            raise LLMError("Ollama 응답이 비어 있습니다.")
        return json.loads(content)

    async def warm_up(self) -> None:
        """서버를 켤 때 모델을 메모리에 미리 올려, 첫 필기가 늦지 않게 한다."""
        try:
            await self.client.post("/api/generate", json={"model": settings.ollama_model, "keep_alive": "30m"})
            log.info("Ollama 모델 준비됨: %s", settings.ollama_model)
        except httpx.HTTPError:
            log.warning("Ollama 모델을 미리 올리지 못했습니다 (%s)", settings.ollama_url)

    async def annotate(self, candidates: list[dict], transcript: str) -> list[dict]:
        data = await self._chat(ANNOTATION_SYSTEM, _annotation_prompt(candidates, transcript), ANNOTATION_SCHEMA,
                                context_tokens=4096)
        return data.get("annotations", [])

    async def summarize(self, pages: list[dict], segments: list[dict], annotations: list[dict]) -> dict:
        return await self._chat(SUMMARY_SYSTEM, _summary_prompt(pages, segments, annotations), SUMMARY_SCHEMA,
                                context_tokens=32768)

    async def research_tips(self, summary: dict) -> list[dict]:
        # 로컬 모델은 웹 검색을 못 해서 링크를 지어낼 수 있으므로, 추가 자료는 만들지 않는다
        return []
