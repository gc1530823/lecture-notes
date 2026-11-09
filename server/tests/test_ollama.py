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
    assert result == {**reply, "terms": []}
    request = seen[0]
    assert request["format"]["required"] == ["annotations", "tasks", "terms"]
    assert request["stream"] is False and request["think"] is False
    assert "[7] 경사하강법" in request["messages"][1]["content"]


def test_missing_model_gives_pull_hint():
    llm = llm_returning(404, {"error": "model not found"}, [])
    with pytest.raises(LLMError, match="ollama pull"):
        asyncio.run(llm.annotate(CANDIDATES, "설명", []))


def test_no_web_tips_in_free_mode():
    llm = llm_returning(200, {}, [])
    assert asyncio.run(llm.research_tips({"pages": []})) == []


def llm_replying(replies: list[dict], seen: list) -> OllamaLLM:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        reply = replies.pop(0)
        return httpx.Response(200, json={"message": {"content": json.dumps(reply, ensure_ascii=False)}})

    return OllamaLLM(transport=httpx.MockTransport(handler))


PAGES = [{"page_no": 1, "text": "경사하강법"}, {"page_no": 2, "text": "역전파"}, {"page_no": 3, "text": "정리"}]
SEGMENTS = [{"page_no": 1, "text": "학습률이 크면 발산해요."}, {"page_no": 2, "text": "연쇄 법칙을 반복합니다."}]
QUIZ = {"question": "학습률이 너무 크면?", "choices": ["발산한다", "느려진다", "멈춘다", "같다"],
        "answer_index": 0, "explanation": "최솟값을 지나친다."}


def test_summarize_goes_page_by_page_and_retries_template_answers():
    seen: list = []
    replies = [
        # 1쪽: 처음엔 지시문을 베낀 틀 → 다시 받는다
        {"summary": "2~3문장 핵심 요약", "quiz": {"question": "문항 텍스트", "choices": ["옵션1", "옵션2", "옵션3", "옵션4"],
                                             "answer_index": 0, "explanation": "해설 텍스트"}},
        {"summary": "경사하강법은 기울기 반대 방향으로 이동한다. 학습률이 크면 발산한다.", "quiz": QUIZ},
        # 2쪽: 요약은 진짜, 퀴즈는 틀 → 요약만 남긴다
        {"summary": "역전파는 연쇄 법칙을 반복해 기울기를 구한다.",
         "quiz": {"question": "문항 텍스트", "choices": ["옵션1", "옵션2", "옵션3", "옵션4"], "answer_index": 0,
                  "explanation": ""}},
        {"overview": "경사하강법과 역전파를 배웠다. 학습률과 연쇄 법칙이 핵심이다."},
    ]
    llm = llm_replying(replies, seen)
    result = asyncio.run(llm.summarize(PAGES, SEGMENTS, []))
    assert len(seen) == 4 and seen[1]["options"]["temperature"] > seen[0]["options"]["temperature"]
    assert [p["page_no"] for p in result["pages"]] == [1, 2]  # 받아쓰기가 없는 3쪽은 건너뛴다
    assert result["quiz"] == [{"page_no": 1, **QUIZ}]
    assert result["overview"].startswith("경사하강법과 역전파")


def test_summarize_falls_back_to_page_summaries_when_overview_is_template():
    replies = [{"summary": "경사하강법은 기울기 반대 방향으로 이동한다.", "quiz": QUIZ},
               {"summary": "역전파는 연쇄 법칙을 반복한다.", "quiz": QUIZ},
               {"overview": "5문장 이내 강의 전체 요약"}, {"overview": "전체 요약"}]
    result = asyncio.run(llm_replying(replies, []).summarize(PAGES, SEGMENTS, []))
    assert result["overview"].startswith("경사하강법은")
