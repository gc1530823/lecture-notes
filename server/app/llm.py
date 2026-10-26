"""Claude 호출: 실시간 필기 생성과 강의 후 요약·퀴즈 생성."""

import json
import logging
from typing import Protocol

import anthropic

from .config import settings

log = logging.getLogger(__name__)

ANNOTATION_TYPES = ["explanation", "example", "emphasis", "exam", "notice"]

# 서버 측 fallbacks를 받는 모델. 다른 모델(예: Haiku)로 바꾸면 이 옵션을 보내지 않는다.
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

ANNOTATION_SYSTEM = """당신은 대학 강의를 듣는 학생 대신 강의자료 위에 필기를 해 주는 조교입니다.

입력으로 현재 슬라이드의 텍스트 블록 목록(번호와 내용), 이 슬라이드에 이미 쓴 필기, 교수님의 새 발언(음성 인식 결과)을 받습니다.
새 발언에서 학생이 슬라이드 옆에 적어 둘 만한 내용만 골라 필기로 만드세요.

규칙:
- 슬라이드에 이미 적혀 있는 내용, 이미 쓴 필기와 같은 내용은 쓰지 않습니다.
- 발언에 없는 내용을 지어내지 않습니다. 음성 인식 오류로 보이는 단어는 슬라이드의 용어로 바로잡습니다.
- 필기 하나는 한국어 두 줄(약 60자) 이내로, 학생 노트처럼 간결하게 씁니다.
- block_id에는 그 필기와 가장 관련 있는 블록 번호를 넣고, 맞는 블록이 없으면 -1을 넣습니다.
- type은 다음 중 하나입니다.
  - explanation: 슬라이드에 없는 보충 설명이나 풀이 과정
  - example: 교수님이 든 예시나 사례
  - emphasis: "중요하다", "꼭 기억하라" 같은 강조
  - exam: "시험에 나온다", "출제한다" 같은 시험 관련 발언
  - notice: 과제, 일정, 공지, 질문과 답변
- 잡담, 인사, 필기할 가치가 없는 발언뿐이면 빈 목록을 반환합니다."""

ANNOTATION_SCHEMA = {
    "type": "object",
    "properties": {
        "annotations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "block_id": {"type": "integer"},
                    "type": {"type": "string", "enum": ANNOTATION_TYPES},
                    "text": {"type": "string"},
                },
                "required": ["block_id", "type", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["annotations"],
    "additionalProperties": False,
}

SUMMARY_SYSTEM = """당신은 대학 강의를 복습용으로 정리하는 조교입니다.
강의자료의 페이지별 텍스트, 페이지별 받아쓰기, 강의 중 만든 필기를 받습니다.

만들 것:
- overview: 강의 전체 요약 (5문장 이내)
- pages: 내용이 있는 페이지마다 핵심 요약 (2~3문장)
- quiz: 복습 퀴즈 5~10문항. 시험(exam)·강조(emphasis) 필기가 붙은 페이지를 우선 출제합니다.
  - 각 문항은 보기 4개(choices), 정답 번호(answer_index, 0부터 시작), 해설(explanation), 출처 페이지(page_no)를 가집니다.

강의자료와 받아쓰기에 있는 내용만 사용하고, 한국어로 씁니다."""

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"page_no": {"type": "integer"}, "summary": {"type": "string"}},
                "required": ["page_no", "summary"],
                "additionalProperties": False,
            },
        },
        "quiz": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "page_no": {"type": "integer"},
                    "question": {"type": "string"},
                    "choices": {"type": "array", "items": {"type": "string"}},
                    "answer_index": {"type": "integer"},
                    "explanation": {"type": "string"},
                },
                "required": ["page_no", "question", "choices", "answer_index", "explanation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overview", "pages", "quiz"],
    "additionalProperties": False,
}


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    async def annotate(self, blocks: list[dict], existing: list[dict], transcript: str) -> list[dict]: ...

    async def summarize(self, pages: list[dict], segments: list[dict], annotations: list[dict]) -> dict: ...


def _annotation_prompt(blocks: list[dict], existing: list[dict], transcript: str) -> str:
    block_lines = "\n".join(f"[{b['id']}] {b['text']}" for b in blocks) or "(텍스트 없음)"
    existing_lines = "\n".join(f"- ({a['type']}) {a['text']}" for a in existing) or "(없음)"
    return (
        f"<slide_blocks>\n{block_lines}\n</slide_blocks>\n\n"
        f"<existing_notes>\n{existing_lines}\n</existing_notes>\n\n"
        f"<new_speech>\n{transcript}\n</new_speech>"
    )


def _summary_prompt(pages: list[dict], segments: list[dict], annotations: list[dict]) -> str:
    parts = []
    for page in pages:
        no = page["page_no"]
        speech = " ".join(s["text"] for s in segments if s["page_no"] == no)
        notes = "\n".join(f"- ({a['type']}) {a['text']}" for a in annotations if a["page_no"] == no)
        parts.append(
            f'<page no="{no}">\n<slide>\n{page["text"]}\n</slide>\n'
            f"<speech>\n{speech or '(없음)'}\n</speech>\n<notes>\n{notes or '(없음)'}\n</notes>\n</page>"
        )
    unmatched = " ".join(s["text"] for s in segments if s["page_no"] is None)
    if unmatched:
        parts.append(f"<speech_without_page>\n{unmatched}\n</speech_without_page>")
    return "\n\n".join(parts)


def _response_json(response) -> dict:
    if response.stop_reason == "refusal":
        raise LLMError("모델이 요청을 거절했습니다.")
    if response.stop_reason == "max_tokens":
        raise LLMError("응답이 max_tokens에서 잘렸습니다.")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise LLMError("응답에 텍스트가 없습니다.")
    return json.loads(text)


class ClaudeLLM:
    def __init__(self) -> None:
        self.client = anthropic.AsyncAnthropic()

    @staticmethod
    def _request(model: str, effort: str, system: str, prompt: str, schema: dict, max_tokens: int) -> dict:
        params = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        }
        if model in FALLBACK_MODELS:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    async def annotate(self, blocks: list[dict], existing: list[dict], transcript: str) -> list[dict]:
        params = self._request(
            settings.annotation_model,
            settings.annotation_effort,
            ANNOTATION_SYSTEM,
            _annotation_prompt(blocks, existing, transcript),
            ANNOTATION_SCHEMA,
            max_tokens=8000,
        )
        response = await self.client.beta.messages.create(**params)
        return _response_json(response)["annotations"]

    async def summarize(self, pages: list[dict], segments: list[dict], annotations: list[dict]) -> dict:
        params = self._request(
            settings.summary_model,
            settings.summary_effort,
            SUMMARY_SYSTEM,
            _summary_prompt(pages, segments, annotations),
            SUMMARY_SCHEMA,
            max_tokens=64000,
        )
        # 긴 강의는 출력이 길어서 스트리밍으로 받는다 (HTTP 타임아웃 방지)
        async with self.client.beta.messages.stream(**params) as stream:
            response = await stream.get_final_message()
        return _response_json(response)


class FakeLLM:
    """API 키 없이 앱 흐름을 확인하기 위한 가짜 응답."""

    async def annotate(self, blocks: list[dict], existing: list[dict], transcript: str) -> list[dict]:
        block_id = blocks[0]["id"] if blocks else -1
        type_ = "exam" if "시험" in transcript else "emphasis" if "중요" in transcript else "explanation"
        return [{"block_id": block_id, "type": type_, "text": transcript[:60]}]

    async def summarize(self, pages: list[dict], segments: list[dict], annotations: list[dict]) -> dict:
        spoken = [p for p in pages if any(s["page_no"] == p["page_no"] for s in segments)]
        return {
            "overview": f"받아쓰기 {len(segments)}문장, 필기 {len(annotations)}개로 정리한 강의입니다.",
            "pages": [{"page_no": p["page_no"], "summary": p["text"][:100]} for p in spoken],
            "quiz": [
                {
                    "page_no": p["page_no"],
                    "question": f"{p['page_no']}페이지에서 다룬 내용은?",
                    "choices": [p["text"][:30] or "(내용)", "보기 2", "보기 3", "보기 4"],
                    "answer_index": 0,
                    "explanation": "가짜 응답입니다.",
                }
                for p in spoken[:5]
            ],
        }


def make_llm() -> LLM:
    return FakeLLM() if settings.llm_mode == "fake" else ClaudeLLM()
