#!/bin/bash
# LUNE server setup for Oracle Cloud Always Free (Ubuntu 24.04).
# Paste this whole text into: Advanced options > Management > Paste cloud-init script.
# Replace ONLY the text inside the quotes on the next 4 lines. Keep the quotes.
# (ASCII only: the Oracle console breaks on non-ASCII characters in this box.)
GROQ_API_KEY="PUT_GROQ_KEY_HERE"
INVITE_CODE="PUT_INVITE_CODE_HERE"
TS_AUTHKEY="PUT_TAILSCALE_KEY_HERE"
HF_TOKEN="PUT_HUGGINGFACE_READ_TOKEN_HERE"
REPO="kimheejin0823/lune-server"

exec > /var/log/lune-setup.log 2>&1
set -x
export DEBIAN_FRONTEND=noninteractive

for i in $(seq 1 1080); do
  curl -fsS -m 5 -o /dev/null https://huggingface.co && break
  sleep 10
done

apt-get update
apt-get install -y python3-venv python3-pip ffmpeg curl ca-certificates
id lune >/dev/null 2>&1 || useradd -r -m -d /var/lib/lune -s /usr/sbin/nologin lune
mkdir -p /etc/lune /opt/lune /var/lib/lune/uploads
chown -R lune:lune /var/lib/lune

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
# Small free server (AMD E2.1.Micro, 1GB RAM): add 4GB swap and skip the heavy local Whisper
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$MEM_MB" -lt 3000 ]; then
  if [ ! -f /swapfile ]; then
    fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
    echo "/swapfile none swap sw 0 0" >> /etc/fstab
  fi
  sed -i 's/^STT_MODE=hybrid/STT_MODE=groq/' /etc/lune/env
fi
echo -n "$HF_TOKEN" > /etc/lune/hf_token
chmod 600 /etc/lune/env /etc/lune/hf_token

cat > /opt/lune/update.sh <<'EOF'
#!/bin/bash
set -e
REPO="kimheejin0823/lune-server"
TOKEN=$(cat /etc/lune/hf_token)
URL="https://huggingface.co/$REPO/resolve/main"
NEW=$(curl -fsSL -H "Authorization: Bearer $TOKEN" "$URL/VERSION")
OLD=$(cat /opt/lune/app/VERSION 2>/dev/null || true)
[ "$NEW" = "$OLD" ] && exit 0
echo "LUNE update: $OLD -> $NEW"
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

curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --auth-key="$TS_AUTHKEY" --hostname=lune
tailscale funnel --bg 8000
tailscale funnel status
echo "LUNE setup done"
