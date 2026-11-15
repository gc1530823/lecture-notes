#!/bin/bash
# Runs as root on the Oracle server after each code update (deploy/oracle/cloud-init.sh -> update.sh).
# Put system-level needs here (apt packages, settings). Must be safe to run many times.
export DEBIAN_FRONTEND=noninteractive
command -v ffmpeg >/dev/null || apt-get install -y ffmpeg
exit 0
