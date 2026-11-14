# LUNE 서버 (허깅페이스 무료 서버, 24시간). deploy/hf/publish.py 가 이 폴더와 서버·웹 결과물을 모아 올린다.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
WORKDIR /app
COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt huggingface_hub
COPY --chown=user server server
COPY --chown=user web/dist web/dist
COPY --chown=user hf/start.sh hf/hf_backup.py ./
USER user
# 비밀값(서버 설정 › Secrets): GROQ_API_KEY · INVITE_CODE · HF_TOKEN(자료 백업용)
ENV HOME=/home/user \
    DB_PATH=/home/user/data/lecture_notes.db \
    UPLOAD_DIR=/home/user/data/uploads \
    LLM_MODE=groq \
    STT_MODE=hybrid \
    WHISPER_MODEL=small \
    PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["bash", "start.sh"]
