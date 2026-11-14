#!/bin/bash
# 켜질 때: 백업에서 자료를 되살리고 → 5분마다 백업 → 서버
mkdir -p /home/user/data/uploads
python hf_backup.py restore || echo "백업 되살리기 건너뜀"
python hf_backup.py loop &
cd server && exec uvicorn app.main:app --host 0.0.0.0 --port 7860 --proxy-headers --forwarded-allow-ips '*'
