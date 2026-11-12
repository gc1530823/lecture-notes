"""공개 강의 결과 폴더(result/* 브랜치: 강의자료.pdf · 받아쓰기.txt · 쪽정답.json)로 쪽 추적만 다시 돌려 채점한다.
쪽 추적(app/alignment.py)을 고친 뒤 Groq 없이 바로 비교할 때. 사용법: python scripts/replay_pages.py <결과 폴더> [v]"""
import json, re, sys
import os
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import app.alignment as al
from app.pdf_parser import parse_pdf
from slide_truth import truth_at
d = sys.argv[1]
pages = parse_pdf(open(f"{d}/강의자료.pdf", "rb").read())
truth = json.load(open(f"{d}/쪽정답.json"))["pages"]
lines = [(int(m[1])*60+int(m[2]), m[4]) for m in (re.match(r"\[(\d+):(\d+)\]\s*\((\d+)쪽\)\s*(.*)", l) for l in open(f"{d}/받아쓰기.txt")) if m]
tr = al.PageTracker(al.PageIndex([p["text"] for p in pages])); tr.user_viewed(1, manual=False)
tot = ok = near = 0; out = []
for t, text in lines:
    e = tr.observe(text, t*1000, now=1e6)
    real = truth_at(truth, t)
    out.append((t, e.page_no, real))
    if real is None: continue
    tot += 1; ok += e.page_no == real; near += abs(e.page_no - real) <= 1
print(f"{d.rsplit('/',1)[-1]}: {tot}문장 정확 {ok/tot:.0%} · ±1 {near/tot:.0%}")
if len(sys.argv) > 2: print(" ".join(f"{t//60}:{t%60:02d}={p}/{r}" for t, p, r in out))
