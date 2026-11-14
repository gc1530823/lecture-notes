import os

# 시험 중에는 한국어 글자 인식 모델(약 10MB)을 인터넷에서 받지 않는다
os.environ.setdefault("OCR_DISABLED", "1")
