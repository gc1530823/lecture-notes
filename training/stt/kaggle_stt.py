"""Kaggle 무료 GPU에서 받아쓰기 AI를 가르친다 (GitHub Actions의 Train speech AI on Kaggle 워크플로가 올려서 실행한다).

finetune_whisper.py는 같은 폴더에 함께 올라온다(코드 안에 넣어 보냄). 결과는 /kaggle/working/ 에 남긴다.
"""

import os
import shutil
import subprocess
import sys

work = "/kaggle/working"
os.chdir(work)
# 오디오 읽기가 datasets 4부터 torchcodec으로 바뀌어 3.x로 둔다
# transformers·torch는 Kaggle에 깔린 것을 쓰고(파이썬 3.13), 오디오를 읽는 datasets만 3.x로 고정한다
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "datasets[audio]>=3.6,<4", "jiwer>=3.0",
                "ctranslate2>=4.6", "soundfile", "librosa"], check=True)
open("finetune_whisper.py", "w", encoding="utf-8").write(SCRIPT)  # noqa: F821 (워크플로가 앞에 붙여 넣는다)
subprocess.run([sys.executable, "finetune_whisper.py", *ARGS], check=True)  # noqa: F821
shutil.rmtree("whisper-ko-run", ignore_errors=True)
shutil.make_archive("whisper-ko-ct2", "zip", ".", "whisper-ko-ct2")
shutil.make_archive("whisper-ko-hf", "zip", ".", "whisper-ko-hf")
shutil.rmtree("whisper-ko-ct2", ignore_errors=True)
shutil.rmtree("whisper-ko-hf", ignore_errors=True)
print("완료:", os.listdir(work))
