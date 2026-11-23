#!/usr/bin/env bash
# 디코이 안 moa-notify = 회사 표준 구성 그대로(세 서버 공통 — 디코이에만 없으면 단서). 탐지 판단은 팜이 한다(Acalvio: 디코이 밖에서 감시, 11/23 원문 확인)
# guest.sh offline 뒤 마운트된 디스크에 비부팅 nspawn으로(게스트 로그에 설치 명령이 안 남음). 설치 경로·유닛은 servers/detection/moa-notify/install.sh와 같다
#   sudo ./moa.sh <이름> <moa_notify.py> <moa-notify.service> <config.json>
set -euo pipefail
n=${1:?이름}; py=${2:?}; unit=${3:?}; cfg=${4:?}
R=/var/lib/machines/$n
findmnt -rno SOURCE "$R" >/dev/null || { echo "$R 가 마운트돼 있지 않음" >&2; exit 2; }
install -d -m 0755 "$R/opt/moa-notify"; install -m 0644 "$py" "$R/opt/moa-notify/moa_notify.py"
install -d -m 0700 "$R/etc/moa-notify" "$R/var/lib/moa-notify"; install -m 0600 "$cfg" "$R/etc/moa-notify/config.json"
install -m 0644 "$unit" "$R/etc/systemd/system/moa-notify.service"
systemd-nspawn -q --settings=false --register=no --private-network -D "$R" --pipe -- systemctl enable moa-notify >/dev/null 2>&1
echo "moa-notify 설치: $n"
