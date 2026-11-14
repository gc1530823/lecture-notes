"""AI 개념 설명 겹침 없애기: 쪽마다 따로 만들어서 '교착 상태 (Deadlock)'와 '교착 상태',
'교착 예방'과 '교착 상태 예방'처럼 같은 개념이 여러 번 나온다. 이름을 맞춰 보고 하나로 합친다."""

import re


def _key(term: str) -> str:
    base = re.sub(r"\([^)]*\)", "", term)               # 괄호 안 영어 이름은 빼고
    base = re.sub(r"\s+|상태|의|하기|이란|란$", "", base)  # 띄어쓰기 · '상태' · 군더더기 말
    return base.lower()


def _english(term: str) -> str:
    m = re.search(r"\(([^)]*[A-Za-z][^)]*)\)", term)
    return re.sub(r"\s+", "", m.group(1)).lower() if m else ""


def merge_concepts(items: list[dict]) -> list[dict]:
    """같은 개념은 한 번만: 가장 자세한 설명을 남기고, 다른 쪽의 예시를 붙이고, 쪽 번호를 모은다"""
    out: list[dict] = []
    for item in items:
        term = str(item.get("term", "")).strip()
        same = next((o for o in out if _key(o["term"]) == _key(term)
                     or (_english(term) and _english(term) == _english(o["term"]))), None)
        if same is None:
            out.append({**item, "pages": [item["page_no"]] if item.get("page_no") else []})
            continue
        if item.get("page_no") and item["page_no"] not in same["pages"]:
            same["pages"].append(item["page_no"])
        here, there = str(item.get("definition", "")), str(same.get("definition", ""))
        if len(here) > len(there):
            example = re.search(r"예\)[^\n]*", there)
            same["definition"] = here + (f" {example.group(0)}" if example and "예)" not in here else "")
        elif "예)" in here and "예)" not in there:
            same["definition"] = there + " " + re.search(r"예\)[^\n]*", here).group(0)
        if len(str(item.get("example") or "")) > len(str(same.get("example") or "")):
            same["example"] = item["example"]
        if "(" in term and "(" not in same["term"]:  # 영어 이름이 붙은 쪽 이름을 쓴다
            same["term"] = term
    return out
