#!/bin/bash
# LUNE 서버 설치 (오라클 클라우드 평생 무료, 우분투 24.04)
# 오라클에서 인스턴스를 만들 때 '고급 옵션 › 관리 › cloud-init 스크립트'에 이 글 전체를 붙여 넣고,
# 아래 네 줄의 따옴표 안만 바꿔 주세요. 서버가 처음 켜질 때 알아서 설치하고 실행해요 (10~15분).
# =====================================================================
GROQ_API_KEY="여기에_Groq_키"            # gsk_ 로 시작하는 키
INVITE_CODE="여기에_초대_코드"            # 친구들이 가입할 때 넣을 말
TS_AUTHKEY="여기에_테일스케일_인증키"      # tskey-auth- 로 시작하는 키
HF_TOKEN="여기에_허깅페이스_읽기_토큰"     # hf_ 로 시작하는 토큰 (서버 코드 받기용)
# =====================================================================
REPO="kimheejin0823/lune-server"

exec > /var/log/lune-setup.log 2>&1
set -x
export DEBIAN_FRONTEND=noninteractive

# 0. 인터넷이 연결될 때까지 기다린다 (공용 IP 를 서버를 만든 뒤에 붙여도 이어서 설치되게, 최대 3시간)
for i in $(seq 1 1080); do
  curl -fsS -m 5 -o /dev/null https://huggingface.co && break
  sleep 10
done

# 1. 필요한 프로그램
apt-get update
apt-get install -y python3-venv python3-pip ffmpeg curl ca-certificates
id lune >/dev/null 2>&1 || useradd -r -m -d /var/lib/lune -s /usr/sbin/nologin lune
mkdir -p /etc/lune /opt/lune /var/lib/lune/uploads
chown -R lune:lune /var/lib/lune

# 2. 비밀값 (서버 안에만, 다른 사람은 못 읽게)
cat > /etc/lune/env <<EOF
GROQ_API_KEY=$GROQ_API_KEY
INVITE_CODE=$INVITE_CODE
LLM_MODE=groq
STT_MODE=hybrid
WHISPER_MODEL=small
DB_PATH=/var/lib/lune/lune.db
UPLOAD_DIR=/var/lib/lune/uploads
HF_HOME=/var/lib/lune/.cache/huggingface
EOF
echo -n "$HF_TOKEN" > /etc/lune/hf_token
chmod 600 /etc/lune/env /etc/lune/hf_token

# 3. 업데이트 스크립트: 새 버전이 있으면 받아서 바꾸고 다시 켠다 (처음 설치도 이걸로)
cat > /opt/lune/update.sh <<'EOF'
#!/bin/bash
set -e
REPO="kimheejin0823/lune-server"
TOKEN=$(cat /etc/lune/hf_token)
URL="https://huggingface.co/$REPO/resolve/main"
NEW=$(curl -fsSL -H "Authorization: Bearer $TOKEN" "$URL/VERSION")
OLD=$(cat /opt/lune/app/VERSION 2>/dev/null || true)
[ "$NEW" = "$OLD" ] && exit 0
echo "LUNE 업데이트: $OLD -> $NEW"
rm -rf /opt/lune/new && mkdir -p /opt/lune/new
curl -fsSL -H "Authorization: Bearer $TOKEN" "$URL/lune-server.tar.gz" | tar xz -C /opt/lune/new
[ -d /opt/lune/venv ] || python3 -m venv /opt/lune/venv
if ! cmp -s /opt/lune/new/lune/server/requirements.txt /opt/lune/app/server/requirements.txt 2>/dev/null; then
  /opt/lune/venv/bin/pip install -q --upgrade pip
  /opt/lune/venv/bin/pip install -q -r /opt/lune/new/lune/server/requirements.txt
fi
rm -rf /opt/lune/old
[ -d /opt/lune/app ] && mv /opt/lune/app /opt/lune/old
mv /opt/lune/new/lune /opt/lune/app && rm -rf /opt/lune/new
chown -R lune:lune /opt/lune/app
systemctl restart lune 2>/dev/null || true
EOF
chmod 700 /opt/lune/update.sh
/opt/lune/update.sh

# 4. 서버를 계속 켜 두기 (꺼지면 다시 켜고, 컴퓨터가 다시 켜져도 자동으로)
cat > /etc/systemd/system/lune.service <<'EOF'
[Unit]
Description=LUNE server
After=network-online.target
Wants=network-online.target

[Service]
User=lune
WorkingDirectory=/opt/lune/app/server
EnvironmentFile=/etc/lune/env
ExecStart=/opt/lune/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/lune-update.service <<'EOF'
[Unit]
Description=LUNE update check
[Service]
Type=oneshot
ExecStart=/opt/lune/update.sh
EOF
cat > /etc/systemd/system/lune-update.timer <<'EOF'
[Unit]
Description=LUNE update check every hour
[Timer]
OnBootSec=5min
OnUnitActiveSec=1h
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now lune lune-update.timer

# 5. 고정 주소 (테일스케일 퍼널): https://lune.<내 테일넷>.ts.net
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --auth-key="$TS_AUTHKEY" --hostname=lune
tailscale funnel --bg 8000
tailscale funnel status
echo "LUNE 설치 끝"
