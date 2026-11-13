#!/bin/bash
# 쫑긋 강의노트 서버 (Linux): python3(3.11+), node, ffmpeg, cloudflared 가 있어야 해요.
#   Ubuntu: sudo apt install python3 python3-venv nodejs npm ffmpeg
#   cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
cd "$(dirname "$0")" || exit 1
for cmd in python3 node ffmpeg; do command -v "$cmd" >/dev/null || { echo "[!] $cmd 가 없어요 (위 주석의 설치 명령 참고)"; exit 1; }; done
exec python3 run.py "$@"
