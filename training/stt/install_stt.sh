#!/usr/bin/env bash
# 우리 받아쓰기 AI 설치 (Codespaces나 내 컴퓨터): 릴리스 "받아쓰기 AI (최신)"를 받아 풀어 둔다.
#   bash training/stt/install_stt.sh
# 그다음 서버를 다시 켜면(또는 Codespace를 다시 열면) 이 서버의 받아쓰기(Groq 한도에 걸렸을 때, 또는 STT_MODE=whisper)가 우리 AI로 바뀐다.
set -euo pipefail
DIR="${1:-$HOME/.cache/lecture-notes-stt}"
mkdir -p "$DIR" && cd "$DIR"
gh release download stt-latest --repo "${GITHUB_REPOSITORY:-gc1530823/lecture-notes}" --pattern whisper-ko-ct2.zip --clobber
rm -rf whisper-ko-ct2 && python3 -m zipfile -e whisper-ko-ct2.zip . && rm whisper-ko-ct2.zip
echo "설치 끝: $DIR/whisper-ko-ct2 — 서버를 다시 켜면 우리 받아쓰기 AI를 써요."
