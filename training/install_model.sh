#!/usr/bin/env bash
# 우리 AI 설치 (Codespaces나 내 컴퓨터, Ollama가 있을 때): 릴리스 "우리 AI (최신)"를 받아 이어 붙이고 Ollama에 등록한다.
#   bash training/install_model.sh
# 그다음 서버를 다시 켜면(또는 Codespace를 다시 열면) 강의 뒤 정리를 우리 AI가 맡는다 (LLM_MODE=hybrid).
set -euo pipefail
DIR="${1:-$HOME/.cache/lecture-notes-model}"
mkdir -p "$DIR" && cd "$DIR"
rm -f lecture-notes.gguf.part* lecture-notes.gguf
echo "릴리스에서 받는 중 (약 2.5GB)…"
gh release download model-latest --repo "${GITHUB_REPOSITORY:-gc1530823/lecture-notes}" --pattern 'lecture-notes.gguf.part*' --pattern Modelfile --clobber
cat lecture-notes.gguf.part* > lecture-notes.gguf && rm lecture-notes.gguf.part*
sed -i 's|^FROM .*|FROM ./lecture-notes.gguf|' Modelfile
ollama create lecture-notes -f Modelfile
rm lecture-notes.gguf   # Ollama가 자기 저장소에 복사해 두었다
echo "설치 끝: 'ollama run lecture-notes'로 확인할 수 있어요. 서버를 다시 켜면 강의 뒤 정리를 우리 AI가 맡아요."
