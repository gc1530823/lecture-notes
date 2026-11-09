"""모아 둔 AI 요청·답(TRAINING_LOG=1)을 우리 AI 학습 데이터로 만든다.

- 필기 작업(annotate)은 사용자가 고친 기록(feedback 표)으로 바로잡는다: 지운 필기는 빼고, 고친 글은 고친 글로, 옮긴 필기는 옮긴 쪽으로.
  = "큰 AI가 쓴 것"이 아니라 "학생이 맞다고 인정한 것"을 배우게 된다.
- 같은 요청은 한 번만, 검증용(val)은 학습용(train)과 다른 강의에서 고른다 (본 적 없는 강의로 실력을 재려고).

사용법 (server 폴더에서):
  python scripts/export_training.py [--out ../training/data] [--tasks annotate,flashcards] [--val 0.1]
결과: out/train.jsonl, out/val.jsonl  (한 줄 = {"task", "schema", "messages": [system, user, assistant]})
"""

import argparse
import glob
import hashlib
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import settings  # noqa: E402
from app.db import Database  # noqa: E402


def load_raw(directory: str) -> list[dict]:
    records = []
    for path in sorted(glob.glob(os.path.join(directory, "raw-*.jsonl"))):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass  # 쓰다 끊긴 줄
    return records


def corrections(feedback: list[dict]) -> dict[tuple[str, str], dict]:
    """(강의, AI가 처음 쓴 글) → 마지막 상태 {deleted, text, page_no}"""
    final: dict[tuple[str, str], dict] = {}
    for f in feedback:
        key = (f["session_id"], f["original_text"])
        state = final.setdefault(key, {"deleted": False, "text": None, "page_no": None})
        if f["action"] == "delete":
            state["deleted"] = True
        elif f["action"] == "edit":
            state["text"] = f["new_text"]
        elif f["action"] == "move":
            state["page_no"] = f["new_page_no"]
    return final


def apply_corrections(record: dict, fixes: dict) -> tuple[dict, int]:
    """필기 답을 사용자가 고친 대로 바꾼다. 바꾼 개수도 돌려준다."""
    output = dict(record["output"])
    changed = 0
    kept = []
    for item in output.get("annotations", []):
        fix = fixes.get((record.get("session_id"), item.get("text")))
        if fix is None:
            kept.append(item)
            continue
        changed += 1
        if fix["deleted"]:
            continue
        item = dict(item)
        if fix["text"]:
            item["text"] = fix["text"]
        if fix["page_no"]:
            item["page_no"] = fix["page_no"]
        kept.append(item)
    output["annotations"] = kept
    return output, changed


def split_key(record: dict) -> float:
    """강의 단위로 0~1 사이 값 (같은 강의는 모두 train이거나 모두 val)"""
    key = record.get("session_id") or record["id"]
    return int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def main(out: str, tasks: set[str] | None, val_ratio: float) -> None:
    records = load_raw(settings.training_dir)
    if not records:
        print(f"학습 데이터가 없어요: {settings.training_dir}/raw-*.jsonl (서버를 TRAINING_LOG=1 로 켜고 강의를 녹음하세요)")
        return
    fixes = corrections(Database(settings.db_path).list_feedback()) if os.path.exists(settings.db_path) else {}

    seen, rows, stats, corrected = set(), {"train": [], "val": []}, Counter(), 0
    for r in records:
        if tasks and r["task"] not in tasks:
            continue
        digest = hashlib.sha1((r["system"] + "\0" + r["prompt"]).encode()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        output = r["output"]
        if r["task"] == "annotate":
            output, n = apply_corrections(r, fixes)
            corrected += n
        row = {"task": r["task"], "schema": r.get("schema"), "messages": [
            {"role": "system", "content": r["system"]},
            {"role": "user", "content": r["prompt"]},
            {"role": "assistant", "content": json.dumps(output, ensure_ascii=False)},
        ]}
        part = "val" if split_key(r) < val_ratio else "train"
        rows[part].append(row)
        stats[(r["task"], part)] += 1

    os.makedirs(out, exist_ok=True)
    for part, items in rows.items():
        with open(os.path.join(out, f"{part}.jsonl"), "w", encoding="utf-8") as f:
            for row in items:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"요청 {len(records)}개 → 학습 {len(rows['train'])}개 · 검증 {len(rows['val'])}개 (겹친 요청 {len(records) - len(seen)}개 뺌)")
    print(f"사용자가 고친 필기 {corrected}개를 반영했어요")
    for task in sorted({t for t, _ in stats}):
        print(f"  {task:15} 학습 {stats[(task, 'train')]:5} · 검증 {stats[(task, 'val')]:4}")
    print(f"저장: {out}/train.jsonl, {out}/val.jsonl")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "..", "training", "data"))
    parser.add_argument("--tasks", default="", help="쉼표로 구분 (비우면 전부)")
    parser.add_argument("--val", type=float, default=0.1)
    args = parser.parse_args()
    main(args.out, set(filter(None, args.tasks.split(","))) or None, args.val)
