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


NEW_Q = {"question": "체인 룰이 없다면 역전파에서 어떤 일이 어려워질까요?", "choices": ["층마다 기울기를 이어 붙이기", "데이터 불러오기", "학습률 정하기", "가중치 저장하기"],
         "answer_index": 0, "explanation": "역전파는 연쇄 법칙으로 층마다 기울기를 이어 계산합니다."}
NEW_Q2 = {"question": "손실이 줄지 않고 점점 커진다면 가장 먼저 의심할 것은?", "choices": ["학습률이 너무 크다", "데이터가 많다", "층이 적다", "배치가 작다"],
          "answer_index": 0, "explanation": "학습률이 크면 최솟값을 지나쳐 발산합니다."}


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
        # 강의 전체로 따로 낸 퀴즈: 처음엔 "몇 쪽 내용은?" 꼴뿐 → 다시 받는다 → 이해를 묻는 새 문제
        {"quiz": [{**QUIZ, "page_no": 1, "question": "1쪽에서 다룬 내용은?"}]},
        {"quiz": [{**QUIZ, "page_no": 1}, {**NEW_Q, "page_no": 2}, {**NEW_Q2, "page_no": 1}]},
    ]
    llm = llm_replying(replies, seen)
    result = asyncio.run(llm.summarize(PAGES, SEGMENTS, []))
    assert len(seen) == 6 and seen[1]["options"]["temperature"] > seen[0]["options"]["temperature"]
    assert [p["page_no"] for p in result["pages"]] == [1, 2]  # 받아쓰기가 없는 3쪽은 건너뛴다
    assert [q["question"] for q in result["quiz"]] == [QUIZ["question"], NEW_Q["question"], NEW_Q2["question"]]
    assert "이해" in seen[4]["messages"][0]["content"] and "<page_summaries>" in seen[4]["messages"][1]["content"]
    assert result["overview"].startswith("경사하강법과 역전파")


def test_summarize_falls_back_to_page_summaries_when_overview_is_template():
    replies = [{"summary": "경사하강법은 기울기 반대 방향으로 이동한다.", "quiz": QUIZ},
               {"summary": "역전파는 연쇄 법칙을 반복한다.", "quiz": QUIZ},
               {"overview": "5문장 이내 강의 전체 요약"}, {"overview": "전체 요약"}, {"quiz": []}, {"quiz": []}]
    result = asyncio.run(llm_replying(replies, []).summarize(PAGES, SEGMENTS, []))
    assert result["overview"].startswith("경사하강법은")


def test_quiz_must_be_new_questions_not_copied_slide_text():
    """퀴즈는 강의를 바탕으로 AI가 새로 낸 문제여야 한다: "몇 쪽 내용은?" 꼴, 슬라이드 문장 베끼기, 틀만 있는 문제는 버린다."""
    from app.ollama_llm import clean_quiz

    slide = "교착 상태는 상호 배제, 점유 대기, 비선점, 순환 대기 네 가지 조건이 모두 만족될 때 발생한다"
    good = {"page_no": 1, "question": "프린터를 두 프로세스가 서로 기다리는 상황에서, 교착 상태를 깨려면 어느 조건을 없애면 될까요?",
            "choices": ["순환 대기를 끊는다", "CPU를 하나 더 단다", "메모리를 늘린다", "프로세스 우선순위를 같게 한다"],
            "answer_index": 0, "explanation": "네 조건 중 하나만 깨져도 교착 상태는 생기지 않습니다."}
    page_question = {**good, "question": "1쪽에서 다룬 내용은?"}
    copied = {**good, "question": "다음 중 옳은 것은?", "choices": [slide, slide[:30] + "이다", "보기 3입니다 정말로", "보기 4입니다 정말로"]}
    template = {**good, "choices": ["보기 1", "보기 2", "보기 3", "보기 4"]}
    out = clean_quiz([good, page_question, copied, template, {**good, "page_no": 99}], [slide], {1, 2})
    assert [q["question"] for q in out] == [good["question"], good["question"]]
    assert out[1]["page_no"] == 1                                   # 없는 쪽 번호는 첫 쪽으로
