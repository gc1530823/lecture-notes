#!/usr/bin/env bash
# Codespace가 켜질 때마다: Ollama와 서버를 띄우고, iPhone에서 열 주소를 알려 준다.
# 포트는 비공개(기본값)로 둔다: 주소를 열면 GitHub 로그인을 거친 본인만 들어올 수 있다.
cd "$(dirname "$0")/../server"

pgrep -x ollama > /dev/null || (ollama serve > /tmp/ollama.log 2>&1 &)

# 새 Codespace라 자료가 없으면 data-backup 브랜치에서 되살리고, 켜져 있는 동안 10분마다 바뀐 자료를 백업한다
python scripts/backup.py --restore || true
if ! pgrep -f "lecture-notes-backup-loop" > /dev/null; then
  nohup bash -c 'exec -a lecture-notes-backup-loop bash -c "while sleep 600; do python scripts/backup.py; done"' \
    > /tmp/backup.log 2>&1 &
fi
# 새 웹앱(web/)을 빌드해 둔다: 서버가 / 에서 보여 준다 (소스가 바뀌었을 때만 다시)
if [ -d ../web ]; then
  (cd ../web && { [ -d node_modules ] || npm ci --silent; } && \
    { [ -d dist ] && [ -z "$(find src public index.html -newer dist -print -quit 2>/dev/null)" ] || npm run build --silent; }) \
    > /tmp/web-build.log 2>&1 || echo "웹앱 빌드 실패 (/tmp/web-build.log) — 예전 웹앱(/app/)으로 열려요"
fi

# 우리 AI(lecture-notes)가 깔려 있고 Groq 키가 있으면: 수업 중은 Groq, 강의 뒤 정리는 우리 AI (training/install_model.sh)
if [ -z "${LLM_MODE:-}" ] && [ -n "${GROQ_API_KEY:-}" ] && ollama list 2>/dev/null | grep -q "^lecture-notes"; then
  export LLM_MODE=hybrid OLLAMA_MODEL=lecture-notes
  echo "우리 AI를 찾았어요: 강의 뒤 정리는 우리 AI가, 수업 중 필기는 Groq가 맡아요"
fi
pkill -f "uvicorn app.main:app" 2> /dev/null || true
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:4b}" nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/server.log 2>&1 &
for i in $(seq 1 20); do curl -s localhost:8000/health > /dev/null && break; sleep 1; done

URL="https://${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}/"
echo "$URL" > /tmp/lecture-notes-url.txt
echo ""
echo "=============================================="
echo " 핸드폰·컴퓨터 브라우저에서 이 주소를 여세요 (GitHub 로그인 필요, 안드로이드 앱에도 이 주소):"
echo " $URL"
echo "=============================================="
