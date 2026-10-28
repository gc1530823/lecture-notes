#!/usr/bin/env bash
# Codespace를 처음 만들 때 한 번: 서버 패키지, 무료 AI(Ollama + 모델), 받아쓰기 모델을 설치한다.
# Ollama는 공식 설치 스크립트(https://ollama.com/install.sh)로 설치한다 (사용자 동의를 받고 추가함).
set -euo pipefail
cd "$(dirname "$0")/.."

sudo apt-get update -q && sudo apt-get install -y -q ffmpeg zstd > /dev/null
pip install -q -r server/requirements.txt

curl -fsSL https://ollama.com/install.sh | sh
(ollama serve > /tmp/ollama.log 2>&1 &)
for i in $(seq 1 30); do curl -s localhost:11434 > /dev/null && break; sleep 1; done
ollama pull "${OLLAMA_MODEL:-qwen3:4b}"

# 받아쓰기 모델도 미리 받아 둔다 (첫 녹음 파일이 늦지 않게)
python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL:-small}', device='cpu', compute_type='int8')"
echo "설치 완료"
