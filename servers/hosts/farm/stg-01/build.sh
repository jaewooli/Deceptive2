#!/usr/bin/env bash
# stg-01 — 옛 스테이징 서버(재구축 때 확인 없이 같이 옮긴 옛 서버, docs/02-infra-design.md 4절) 컨테이너 루트파일시스템.
# 팜에서 root로. 1단계: Ubuntu 24.04 기본 + 접속 서비스. 역할(nginx→gunicorn·PostgreSQL·옮겨 온 데이터)은 role.sh
#   sudo ./build.sh <투영 주소/접두> <게이트웨이> [DNS] [투영 ENI MAC]
set -euo pipefail
ADDR=${1:?투영 주소/접두}; GW=${2:?게이트웨이}; DNS=${3:-}
NAME=stg-01
ROOT=/var/lib/machines/$NAME
MIRROR=${MIRROR:-http://archive.ubuntu.com/ubuntu}
# EC2 Ubuntu 서버에 기본으로 있는 것에 가깝게(같은 회사 서버와 패키지가 크게 다르면 단서 — D2로 잰다)
PKGS=systemd-sysv,systemd-resolved,dbus,openssh-server,sudo,cron,rsyslog,logrotate,unattended-upgrades,ca-certificates,curl,less,vim-tiny,iproute2,iputils-ping,netbase,tzdata,locales,bash-completion,python3,python3-venv,git,ubuntu-minimal,ubuntu-standard

if [ ! -x "$ROOT/usr/bin/systemctl" ]; then
  debootstrap --components=main,universe --include="$PKGS" noble "$ROOT" "$MIRROR"
fi
cat > "$ROOT/etc/apt/sources.list.d/ubuntu.sources" <<EOF
Types: deb
URIs: $MIRROR
Suites: noble noble-updates noble-backports
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: http://security.ubuntu.com/ubuntu
Suites: noble-security
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
: > "$ROOT/etc/apt/sources.list"
echo "$NAME" > "$ROOT/etc/hostname"
printf '127.0.0.1 localhost\n127.0.1.1 %s\n\n::1 ip6-localhost ip6-loopback\nff02::1 ip6-allnodes\nff02::2 ip6-allrouters\n' "$NAME" > "$ROOT/etc/hosts"
ln -sf /usr/share/zoneinfo/Asia/Seoul "$ROOT/etc/localtime"; echo Asia/Seoul > "$ROOT/etc/timezone"

# 컨테이너 NIC(host0): 투영 주소, 게이트웨이 .1
install -d "$ROOT/etc/systemd/network"
# 투영 디코이의 NIC MAC = 투영 ENI(센서) MAC — 다르면 디코이 안 `ip link`가 이웃 ARP 값과 어긋남(11/23 실측). MAC은 4번째 인자
cat > "$ROOT/etc/systemd/network/10-host0.network" <<EOF
[Match]
Name=host0

[Link]
${4:+MACAddress=$4}

[Network]
Address=$ADDR
Gateway=$GW
${DNS:+DNS=$DNS}
EOF
chroot "$ROOT" systemctl enable systemd-networkd systemd-resolved ssh >/dev/null 2>&1 || true
chroot "$ROOT" systemctl disable systemd-networkd-wait-online >/dev/null 2>&1 || true
echo "built $ROOT ($(du -sh "$ROOT" | cut -f1))"
