"""Kaggle 무료 GPU에서 돌아가는 학습 스크립트 (GitHub Actions의 Train on Kaggle 워크플로가 올려서 실행한다).

/kaggle/input/<데이터셋>/ 에 train.jsonl · val.jsonl · finetune.py · Modelfile 이 있고,
결과(.gguf, Modelfile)는 /kaggle/working/ 에 남겨 워크플로가 내려받는다.
"""

import glob
import os
import shutil
import subprocess
import sys

src = next(os.path.dirname(p) for p in glob.glob("/kaggle/input/**/train.jsonl", recursive=True))
work = "/kaggle/working"
for name in ("train.jsonl", "val.jsonl", "finetune.py", "Modelfile", "settings.txt"):
    if os.path.exists(os.path.join(src, name)):
        shutil.copy(os.path.join(src, name), work)
os.chdir(work)

base = "unsloth/Qwen3-4B-Instruct-2507"
extra = []
if os.path.exists("settings.txt"):
    for line in open("settings.txt"):
        key, _, value = line.strip().partition("=")
        if key == "base" and value:
            base = value
        elif key == "only" and value:
            extra += ["--only", value]
        elif key == "epochs" and value:
            extra += ["--epochs", value]

subprocess.run([sys.executable, "-m", "pip", "install", "-q", "unsloth"], check=True)
subprocess.run([sys.executable, "finetune.py", "--train", "train.jsonl", "--val", "val.jsonl", "--base", base, *extra], check=True)

# 결과만 남긴다 (Kaggle 출력은 /kaggle/working 전체라 중간 파일은 지운다)
# 학습 도구 버전에 따라 "lecture-notes-gguf_gguf/<바탕 모델>.Q4_K_M.gguf"처럼 이름이 바뀌어 저장되기도 한다
found = sorted(glob.glob("**/*.gguf", recursive=True), key=os.path.getsize)
if found:
    shutil.move(found[-1], os.path.join(work, "lecture-notes.gguf"))
for junk in glob.glob("lecture-notes-gguf*") + ["outputs", "unsloth_compiled_cache", "lecture-notes-lora"]:
    shutil.rmtree(junk, ignore_errors=True)
print("완료:", os.listdir(work))
