import asyncio
import json
import os

os.environ.setdefault("LLM_MODE", "fake")

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.llm import LLMError  # noqa: E402
from app.ollama_llm import OllamaLLM  # noqa: E402

CANDIDATES = [{"page_no": 1, "page_id": 1, "blocks": [{"id": 7, "text": "경사하강법"}], "existing": []}]


def llm_returning(status: int, body: dict, seen: list) -> OllamaLLM:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(status, json=body)

    return OllamaLLM(transport=httpx.MockTransport(handler))


def test_annotate_sends_schema_and_parses_reply():
    seen: list = []
    reply = {"annotations": [{"page_no": 1, "block_id": 7, "type": "exam", "text": "시험 출제"}], "tasks": []}
    llm = llm_returning(200, {"message": {"content": json.dumps(reply, ensure_ascii=False)}}, seen)
    result = asyncio.run(llm.annotate(CANDIDATES, "이거 시험에 나와요", []))
    assert result == reply
    request = seen[0]
    assert request["format"]["required"] == ["annotations", "tasks"]
    assert request["stream"] is False and request["think"] is False
    assert "[7] 경사하강법" in request["messages"][1]["content"]


def test_missing_model_gives_pull_hint():
    llm = llm_returning(404, {"error": "model not found"}, [])
    with pytest.raises(LLMError, match="ollama pull"):
        asyncio.run(llm.annotate(CANDIDATES, "설명", []))


def test_no_web_tips_in_free_mode():
    llm = llm_returning(200, {}, [])
    assert asyncio.run(llm.research_tips({"pages": []})) == []
