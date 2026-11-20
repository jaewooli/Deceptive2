#!/usr/bin/env bash
# moa-notify 설치. root로 실행.
#   sudo ./install.sh /path/to/config.json
# config.json은 서버마다 다르다(켜는 감시 항목, 웹훅 주소). 저장소에는 예시만 있다.
set -euo pipefail
cd "$(dirname "$0")"
cfg="${1:?config.json 경로}"

install -d -m 0755 /opt/moa-notify
install -m 0644 moa_notify.py /opt/moa-notify/moa_notify.py
install -d -m 0700 /etc/moa-notify /var/lib/moa-notify
install -m 0600 "$cfg" /etc/moa-notify/config.json
install -m 0644 moa-notify.service /etc/systemd/system/moa-notify.service
systemctl daemon-reload
systemctl enable moa-notify
systemctl restart moa-notify
