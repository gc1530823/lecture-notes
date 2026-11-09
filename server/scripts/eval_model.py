"""우리 AI가 큰 AI(선생님)만큼 하는지 검증 데이터로 잰다.

검증 데이터(val.jsonl)의 요청을 지금 서버 설정의 모델(예: LLM_MODE=ollama OLLAMA_MODEL=lecture-notes)에 다시 보내고,
정답(사용자가 고친 큰 AI의 답)과 비교한다.

- JSON 성공률: 정해진 모양으로 답했는가
- 필기 작업: 필기 개수가 맞는가(없을 때 조용히 있는가), 붙인 문단(block_id)·종류(type)가 맞는가, 글이 얼마나 비슷한가(글자 2-gram F1)
- 다른 작업: 답 글이 얼마나 비슷한가

사용법 (server 폴더에서, Ollama에 모델을 올린 뒤):
  LLM_MODE=ollama OLLAMA_MODEL=lecture-notes python scripts/eval_model.py [--data ../training/data/val.jsonl] [--limit 100]
"""

import argparse
import asyncio
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import settings  # noqa: E402
from app.llm import make_llm  # noqa: E402


def grams(text: str) -> dict[str, int]:
    text = "".join(str(text).split())
    out: dict[str, int] = defaultdict(int)
    for i in range(len(text) - 1):
        out[text[i:i + 2]] += 1
    return out


def f1(a: str, b: str) -> float:
    ga, gb = grams(a), grams(b)
    if not ga and not gb:
        return 1.0
    common = sum(min(n, gb.get(g, 0)) for g, n in ga.items())
    if not common:
        return 0.0
    p, r = common / sum(ga.values()), common / sum(gb.values())
    return 2 * p * r / (p + r)


def flatten_text(value) -> str:
    if isinstance(value, dict):
        return " ".join(flatten_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(flatten_text(v) for v in value)
    return str(value)


def score_annotate(pred: dict, gold: dict) -> dict:
    p, g = pred.get("annotations", []), gold.get("annotations", [])
    result = {"count_ok": float(len(p) == len(g)), "silent_ok": float((not p) == (not g))}
    if p and g:
        # 정답 필기마다 가장 비슷한 예측 필기와 짝짓는다
        pairs = [max(p, key=lambda x: f1(x.get("text", ""), y.get("text", ""))) for y in g]
        result["block_ok"] = sum(x.get("block_id") == y.get("block_id") for x, y in zip(pairs, g)) / len(g)
        result["type_ok"] = sum(x.get("type") == y.get("type") for x, y in zip(pairs, g)) / len(g)
        result["text_f1"] = sum(f1(x.get("text", ""), y.get("text", "")) for x, y in zip(pairs, g)) / len(g)
    return result


async def run(path: str, limit: int) -> None:
    llm = make_llm()
    chat = getattr(llm, "_chat", None)
    if chat is None:
        print("이 모드는 평가할 수 없어요. LLM_MODE=ollama 또는 groq 로 실행하세요.")
        return
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()][:limit]
    print(f"모델: {settings.llm_mode} · {settings.ollama_model if settings.llm_mode == 'ollama' else settings.groq_model} · {len(rows)}개")

    scores: dict[str, list[dict]] = defaultdict(list)
    started = time.monotonic()
    for i, row in enumerate(rows, start=1):
        system, user, gold_msg = row["messages"]
        gold = json.loads(gold_msg["content"])
        schema = row.get("schema") or {"type": "object"}
        try:
            pred = await chat(system["content"], user["content"], schema, context_tokens=8192)
            s = {"json_ok": 1.0}
            s.update(score_annotate(pred, gold) if row["task"] == "annotate" else {"text_f1": f1(flatten_text(pred), flatten_text(gold))})
        except Exception as exc:  # 모델이 엉뚱한 답을 해도 끝까지 잰다
            s = {"json_ok": 0.0}
            print(f"  {i}: 실패 ({type(exc).__name__})")
        scores[row["task"]].append(s)
        if i % 10 == 0:
            print(f"  {i}/{len(rows)} ({time.monotonic() - started:.0f}초)")

    print()
    for task, items in sorted(scores.items()):
        keys = sorted({k for s in items for k in s})
        summary = " · ".join(f"{k} {sum(s[k] for s in items if k in s) / max(1, sum(k in s for s in items)):.0%}" for k in keys)
        print(f"{task:15} ({len(items)}개) {summary}")
    print(f"걸린 시간 {time.monotonic() - started:.0f}초 (1개 평균 {(time.monotonic() - started) / max(1, len(rows)):.1f}초)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=os.path.join(os.path.dirname(__file__), "..", "..", "training", "data", "val.jsonl"))
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    asyncio.run(run(args.data, args.limit))
