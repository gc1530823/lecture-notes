#!/bin/bash
# LUNE 서버 (Mac): 필요한 프로그램을 Homebrew 로 설치하고 run.py 를 실행한다. Finder 에서 두 번 눌러 실행하세요.
# 설치하는 것: Python 3.12, Node.js, FFmpeg, cloudflared, Tailscale (이미 있으면 건너뜀)
cd "$(dirname "$0")" || exit 1

if ! command -v brew >/dev/null 2>&1 && [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi
if ! command -v brew >/dev/null 2>&1; then
  echo "[!] Homebrew 가 필요해요. https://brew.sh 의 설치 명령을 터미널에 붙여 넣어 설치한 뒤 다시 실행해 주세요."
  read -r -p "Enter 를 누르면 닫혀요" _
  exit 1
fi
for pkg in python@3.12:python3.12 node:node ffmpeg:ffmpeg cloudflared:cloudflared; do
  name=${pkg%%:*}; cmd=${pkg##*:}
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "$name 설치 중… (처음 한 번)"
    brew install "$name" || { echo "[!] $name 설치에 실패했어요"; exit 1; }
  fi
done
if ! command -v tailscale >/dev/null 2>&1 && [ ! -d /Applications/Tailscale.app ]; then
  echo "Tailscale 설치 중… (바뀌지 않는 무료 주소, 처음 한 번)"
  brew install --cask tailscale && open -a Tailscale && echo "Tailscale 앱이 열리면 로그인해 주세요."
fi
python3.12 run.py "$@"
read -r -p "Enter 를 누르면 닫혀요" _
