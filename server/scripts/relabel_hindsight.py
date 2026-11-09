"""우리 AI가 선생님(실시간 AI)보다 정확해지게: "나중에 다 보고 쓴" 정답을 만든다.

실시간 필기는 "지금까지 들은 말"만 보고 몇 초 안에 써야 해서 틀리기 쉽다 (쪽을 잘못 고르거나, 곧 이어질 설명을 몰라서).
강의가 끝난 뒤에는 그 요청마다 큰 AI에게
  - 그 뒤 1~2분 동안 이어진 설명 (무엇을 말하려던 건지 알 수 있다)
  - 강의 전체 요약
을 함께 주고, 더 깊이 생각하게 해서(reasoning medium) 같은 모양의 필기를 다시 쓰게 한다.

우리 모델의 입력은 그대로 실시간 때의 요청(앞만 본 것)이고, 정답만 "다 보고 쓴" 것으로 바꾼다
→ 작은 모델이 실시간 선생님보다 나은 필기를 배운다. (scripts/export_training.py가 이 정답을 먼저 쓴다)

사용법 (server 폴더, 그 강의들이 들어 있는 DB가 있을 때):
  GROQ_API_KEY=... DB_PATH=... TRAINING_DIR=... python scripts/relabel_hindsight.py [--limit 200]
"""

import argparse
import asyncio
import glob
import json
import os
import re
import sys
import time
import uuid

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import settings  # noqa: E402
from app.db import Database  # noqa: E402

HINDSIGHT_RULES = """

[강의가 끝난 뒤 다시 쓰기]
이번에는 실시간이 아니라 강의가 끝난 뒤에 이 필기를 다시 씁니다. <after_speech>에는 <new_speech> 바로 뒤에 이어진 설명,
<lecture_summary>에는 강의 전체 요약이 있습니다. 이것들을 참고해 <new_speech> 부분의 필기를 가장 정확하게 씁니다:
- 페이지는 이어진 설명까지 보고 정말 설명하던 슬라이드를 고릅니다. 문단(block_id)도 가장 맞는 것으로.
- 필기 내용은 <new_speech>에서 말한 것만 씁니다 (뒤 설명은 뜻을 정확히 이해하는 데만 쓰고, 뒤에서 처음 나온 내용은 쓰지 않습니다).
- 시험·과제·공지는 실제로 그렇게 말했을 때만. 군말·반복은 필기하지 않습니다. 쓸 것이 없으면 빈 목록이 정답입니다."""


def load(directory: str) -> list[dict]:
    out = []
    for path in sorted(glob.glob(os.path.join(directory, "raw-*.jsonl"))):
        for line in open(path, encoding="utf-8"):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def context_for(record: dict, db: Database) -> str | None:
    """요청의 <new_speech>를 그 강의 받아쓰기에서 찾아, 그 뒤 설명과 강의 요약을 붙인다."""
    sid = record.get("session_id")
    if not sid or db.get_session(sid) is None:
        return None
    m = re.search(r"<new_speech>\n(.*)\n</new_speech>", record["prompt"], re.S)
    if not m:
        return None
    new = norm(m.group(1).replace("(목소리 높임) ", ""))
    segments = db.get_segments(sid)
    joined, ends = "", []
    for s in segments:
        joined += norm(s["text"])
        ends.append(len(joined))
    key = new[-40:]
    pos = joined.find(key)
    if pos < 0:
        return None
    end = pos + len(key)
    after_idx = next((i for i, e in enumerate(ends) if e >= end), len(segments))
    after = " ".join(s["text"] for s in segments[after_idx + 1: after_idx + 1 + 14])[:1800]
    summary = db.get_summary(sid) or {}
    overview = summary.get("overview", "")
    pages = "\n".join(f"- {p['page_no']}쪽: {p['summary']}" for p in summary.get("pages", []))[:1500]
    return (f"\n\n<after_speech>\n{after or '(없음: 강의 끝)'}\n</after_speech>"
            f"\n\n<lecture_summary>\n{overview}\n{pages}\n</lecture_summary>")


async def ask(client: httpx.AsyncClient, system: str, prompt: str, schema: dict) -> dict | None:
    payload = {"model": settings.groq_model, "temperature": 0.1,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
               "response_format": {"type": "json_schema", "json_schema": {"name": "result", "schema": schema}}}
    if "gpt-oss" in settings.groq_model:
        payload["reasoning_effort"] = "medium"  # 실시간(low)보다 깊이 생각한다
    for attempt in range(20):
        res = await client.post("/chat/completions", json=payload)
        if res.status_code == 429:
            await asyncio.sleep(min(float(res.headers.get("retry-after", 10)), 60) + 1)
            continue
        if res.status_code >= 400:
            print(f"    실패 {res.status_code}: {res.text[:120]}", flush=True)
            return None
        try:
            return json.loads(res.json()["choices"][0]["message"]["content"])
        except (KeyError, json.JSONDecodeError):
            return None
    return None


async def main(limit: int) -> None:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise SystemExit("GROQ_API_KEY가 필요합니다")
    records = load(settings.training_dir)
    done = {r.get("hindsight_of") for r in records if r.get("hindsight_of")}
    todo = [r for r in records if r["task"] == "annotate" and not r.get("hindsight_of") and r["id"] not in done]
    db = Database(settings.db_path)
    os.makedirs(settings.training_dir, exist_ok=True)
    out = os.path.join(settings.training_dir, f"raw-{time.strftime('%Y%m')}.jsonl")
    made = changed = skipped = 0
    async with httpx.AsyncClient(base_url="https://api.groq.com/openai/v1", timeout=180,
                                 headers={"Authorization": f"Bearer {key}"}) as client:
        for r in todo[:limit]:
            extra = context_for(r, db)
            if extra is None:
                skipped += 1
                continue
            better = await ask(client, r["system"] + HINDSIGHT_RULES, r["prompt"] + extra, r["schema"])
            if better is None:
                continue
            made += 1
            changed += better != r["output"]
            entry = {**r, "id": uuid.uuid4().hex, "time": time.time(), "model": f"groq:{settings.groq_model}:hindsight",
                     "hindsight_of": r["id"], "output": better}
            with open(out, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"다 보고 다시 쓴 필기 {made}개 (실시간과 달라진 것 {changed}개) · 강의를 못 찾아 건너뜀 {skipped}개")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=200)
    asyncio.run(main(parser.parse_args().limit))
