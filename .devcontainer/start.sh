#!/usr/bin/env bash
# Codespace가 켜질 때마다: Ollama와 서버를 띄우고, iPhone에서 열 주소를 알려 준다.
# 포트는 비공개(기본값)로 둔다: 주소를 열면 GitHub 로그인을 거친 본인만 들어올 수 있다.
cd "$(dirname "$0")/../server"

pgrep -x ollama > /dev/null || (ollama serve > /tmp/ollama.log 2>&1 &)
pkill -f "uvicorn app.main:app" 2> /dev/null || true
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:4b}" nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/server.log 2>&1 &
for i in $(seq 1 20); do curl -s localhost:8000/health > /dev/null && break; sleep 1; done

URL="https://${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}/app/"
echo "$URL" > /tmp/lecture-notes-url.txt
echo ""
echo "=============================================="
echo " iPhone Safari에서 이 주소를 여세요 (GitHub 로그인 필요):"
echo " $URL"
echo "=============================================="
