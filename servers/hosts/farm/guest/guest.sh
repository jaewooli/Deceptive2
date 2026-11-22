#!/usr/bin/env bash
# 팜 디코이 = KVM VM(11/23 결정 B: 컨테이너는 systemd-detect-virt=systemd-nspawn·auditd 불가로 정체가 드러남 — 11/22 B7·D4).
# 공식 클라우드 이미지 디스크 그대로, 진짜 서버처럼 cloud-init으로 첫 부팅. farm에서 root로.
#
#   guest.sh create <이름> <주소/접두> <게이트웨이> <MAC> <메모리MB> <vCPU> <패키지,…> <관리 공개키 파일> [pg]
#       1단계: 디스크(클라우드 이미지 복사·20G) + NoCloud seed → 첫 부팅에서 cloud-init이 full-upgrade·패키지·공통 베이스(base/install.sh)를
#       설치하고 스스로 끈다. 로그인 세션이 아니므로(auid 없음) 공통 감사 규칙 50-user-cmd·sudo 기록에 안 남는다(EC2 user-data 세팅과 같은 모양)
#       빌드 동안만 팜이 NAT로 바깥을 열어 준다(apt·snap·CloudWatch 에이전트). 끝나면 닫는다
#   guest.sh offline <이름>   # VM을 끄고 디스크를 /var/lib/machines/<이름>(+/boot, /boot/efi)에 마운트 — 역할 스크립트는 여기에 비부팅 nspawn으로
#   guest.sh online <이름>    # 마운트 해제, user-data를 기본형으로(빌드 내용 제거, instance-id 유지), VM 시작
#   guest.sh status
# 네트워크: VM NIC = 탭 ve-<이름>(컨테이너 veth와 같은 이름 → farm install.sh의 networkd 파일·relay 규칙 그대로), PCI 슬롯 3 → 게스트 enp0s3
# 로컬 랩 VM과 같게: q35, virtio 디스크·NIC, balloon, cloud-id nocloud(로컬 진짜 서버도 nocloud). EC2(Ec2 데이터소스·IMDS·NVMe·ENA)는 11/28 — HANDOFF 11절
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
LIB=/var/lib/guests; ETC=/etc/guest; LOGD=/var/log/guests
BASE_IMG=/var/cache/decoy/noble-server-cloudimg-amd64.img
IMG_URL=https://cloud-images.ubuntu.com/noble/current
APT_PROXY=${APT_PROXY:-http://10.0.2.2:3142}     # 로컬 랩 전용(진짜 VM에도 같은 01-lab-proxy가 있음). EC2에서는 빈 값
CWAGENT_MODE=${CWAGENT_MODE:-onPremise}
DNS=${GUEST_DNS:-10.0.2.3}                      # 로컬 진짜 VM의 resolved 상위 DNS와 같은 값
export DEBIAN_FRONTEND=noninteractive

need() {
  dpkg -s qemu-system-x86 qemu-utils >/dev/null 2>&1 ||
    apt-get install -y -q --no-install-recommends qemu-system-x86 qemu-utils >/dev/null
  install -d -m 0700 "$LIB" "$ETC"; install -d "$LOGD" /usr/local/lib/relay
  if [ ! -f "$BASE_IMG" ]; then
    install -d "$(dirname "$BASE_IMG")"
    (cd "$(dirname "$BASE_IMG")" && curl -fsSLO "$IMG_URL/SHA256SUMS" && curl -fsSLO "$IMG_URL/$(basename "$BASE_IMG")" &&
     grep " \*\?$(basename "$BASE_IMG")$" SHA256SUMS | sha256sum -c - >/dev/null)
  fi
  install -m 0755 "$HERE/guest-up" "$HERE/guest-stop" /usr/local/lib/relay/
  install -m 0644 "$HERE/guest@.service" /etc/systemd/system/guest@.service
  systemctl daemon-reload
}

uplink() { ip -o route get 1.1.1.1 | sed -n 's/.* dev \([^ ]*\).*/\1/p'; }

seed() {  # seed <이름> <빌드 user-data 여부 1|0> — 마운트된 디스크의 /var/lib/cloud/seed/nocloud/에 쓴다
  # (seed ISO를 붙이면 CD-ROM이 sr0·sr1 두 개가 되고 cloud-init 로그에 cidata 디스크가 남는다 — 진짜 VM은 빈 sr0 하나, 11/23 실측)
  local n=$1 build=$2 d=/var/lib/machines/$1/var/lib/cloud/seed/nocloud
  mounted "$n" || { echo "seed: $n 디스크가 마운트돼 있지 않음" >&2; exit 2; }
  install -d -m 0755 "$d"
  # shellcheck disable=SC1090
  . "$ETC/$n.env"
  cat > "$d/meta-data" <<EOF
instance-id: $INSTANCE_ID
local-hostname: $n
EOF
  # 네트워크: EC2·로컬 진짜 서버의 50-cloud-init.yaml과 같은 모양(MAC 일치 + set-name). DHCP가 없는 구간이라 고정 주소
  cat > "$d/network-config" <<EOF
version: 2
ethernets:
  enp0s3:
    match:
      macaddress: "$MAC"
    set-name: enp0s3
    addresses: [$ADDR]
    routes:
      - to: default
        via: $GW
    nameservers:
      addresses: [$DNS]
EOF
  # 기본 user-data = 로컬 진짜 VM과 같은 내용(infra/local-vm/vm.sh make_seed)
  cat > "$d/user-data" <<EOF
#cloud-config
timezone: Asia/Seoul
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - $(cat "$ETC/$n.pub")
EOF
  if [ "$build" = 1 ]; then
    local pkgs="" p
    for p in ${PKGS//,/ }; do pkgs+="  - $p"$'\n'; done
    local proxy=""   # 로컬 진짜 VM과 같은 파일(lab.sh lan_and_proxy). ${..:+..} 안에 쓰면 따옴표가 빠져 apt 구문 오류(11/23)
    # 패치 수준 = 이웃과 같은 아카이브 스냅숏(블렌딩의 apt_snapshot). 최신으로 올리면 이웃보다 앞서 커널부터 달라진다(11/23: 151 vs 149)
    # 빌드 동안만 — 끝나면 지운다(진짜 서버엔 없는 파일, 이후엔 이웃과 같이 unattended-upgrades로 따라감)
    [ -n "${SNAPSHOT:-}" ] && proxy+="  - path: /etc/apt/apt.conf.d/50-build-snapshot"$'\n'"    content: |"$'\n'"      APT::Snapshot \"$SNAPSHOT\";"$'\n'
    [ -n "$APT_PROXY" ] && proxy+="  - path: /etc/apt/apt.conf.d/01-lab-proxy"$'\n'"    content: |"$'\n'"      Acquire::http::Proxy \"$APT_PROXY\";"$'\n'
    cat >> "$d/user-data" <<EOF
package_update: true
package_upgrade: true
packages:
$pkgs
write_files:
  - path: /run/guest-build/base.tgz
    encoding: b64
    content: $(tar -C "$HERE/base" -czf - . | base64 -w0)
${proxy}runcmd:
  - [sh, -c, "set -e; cd /run/guest-build; tar -xzf base.tgz; CWAGENT_MODE=$CWAGENT_MODE ./install.sh${PG:+; ./install.sh postgresql}; cd /; rm -rf /run/guest-build /etc/apt/apt.conf.d/50-build-snapshot; apt-get update -q"]
power_state:
  mode: poweroff
  condition: true
EOF
  fi
  chmod 600 "$d/user-data"
  cp "$d/user-data" "$LIB/$n-user-data.last"
}

build_egress() {  # on|off <이름> — 빌드 동안만: 게스트 → farm 바깥(NAT). 평소 게스트 응답은 relay 터널로만(pref 50)
  local n=$2 x; x=$(. "$ETC/$n.env"; echo "${ADDR%/*}")
  if [ "$1" = on ]; then
    ip rule show pref 49 | grep -q . || ip rule add pref 49 iif "ve-$n" lookup main
    nft -f - <<EOF
table ip guest_build
delete table ip guest_build
table ip guest_build {
  chain post { type nat hook postrouting priority srcnat; policy accept; ip saddr $x oifname "$(uplink)" masquerade; }
}
EOF
  else
    ip rule del pref 49 2>/dev/null || true
    nft delete table ip guest_build 2>/dev/null || true
  fi
}

create() {
  local n=${1:?이름} addr=${2:?주소/접두} gw=${3:?게이트웨이} mac=${4:?MAC} mem=${5:?메모리} cpus=${6:?vCPU} pkgs=${7:?패키지} key=${8:?공개키} pg=${9:-}
  need
  [ -d "$HERE/base" ] || { echo "base/ 없음(공통 베이스를 이 디렉터리에 같이 보낼 것)" >&2; exit 2; }
  local iid; iid=$( [ -f "$ETC/$n.env" ] && sed -n 's/^INSTANCE_ID=//p' "$ETC/$n.env" || echo "$n-$(date +%s)")
  cat > "$ETC/$n.env" <<EOF
ADDR=$addr
GW=$gw
MAC=$mac
MEM=$mem
CPUS=$cpus
PKGS=$pkgs
PG=$pg
SNAPSHOT=${APT_SNAPSHOT:-}
INSTANCE_ID=$iid
EOF
  install -m 0644 "$key" "$ETC/$n.pub"
  # 팜 쪽 탭: proxy ARP(networkd로 고정 — 스크립트로 넣으면 기본 80-container-ve.network와 경쟁, 11/22)
  # 게이트웨이(.1)를 팜 자신의 주소로 두지 않는다 — 두면 팜이 LAN에서 진짜 라우터(.1)의 ARP를 가로챈다(Linux는 어느 NIC로 온 ARP든
  # 자기 주소면 답함, 11/23 구간 분리 때 발견). 탭엔 링크 로컬만, 게이트웨이 ARP는 proxy ARP가 답한다(팜이 그 주소로 가는 경로를 LAN 쪽에 가짐)
  cat > "/etc/systemd/network/10-ve-$n.network" <<EOF
[Match]
Name=ve-$n

[Network]
Address=169.254.31.2/32
IPv4ProxyARP=yes
LinkLocalAddressing=no
IPv6AcceptRA=no
ConfigureWithoutCarrier=yes
EOF
  networkctl reload 2>/dev/null || true
  systemctl stop "guest@$n" 2>/dev/null || true
  systemctl disable "systemd-nspawn@$n" 2>/dev/null || true; systemctl stop "systemd-nspawn@$n" 2>/dev/null || true
  rm -f "$LIB/$n.qcow2"
  qemu-img convert -q -O qcow2 "$BASE_IMG" "$LIB/$n.qcow2"
  qemu-img resize -q "$LIB/$n.qcow2" 20G      # 로컬 진짜 VM 디스크와 같은 크기(vda 20G). EC2는 8G
  offline "$n"; seed "$n" 1; umount_disk "$n"
  build_egress on "$n"
  : > "$LOGD/$n.log"
  systemctl start "guest@$n"
  echo "1단계: $n 첫 부팅(cloud-init: 업그레이드·패키지·공통 베이스) — 끝나면 스스로 꺼짐"
  local t=0
  while systemctl is-active -q "guest@$n"; do sleep 10; t=$((t + 10)); [ $t -ge 2400 ] && { echo "시간 초과" >&2; break; }; done
  build_egress off "$n"
  grep -a "Cloud-init v.* finished" "$LOGD/$n.log" | tail -1 || true
  grep -aE "Failed|failed" "$LOGD/$n.log" | grep -aiE "cloud|runcmd|scripts_user" | tail -5 || true
  echo "1단계 끝($t초). 역할은: guest.sh offline $n → 역할 스크립트 → guest.sh online $n"
}

mounted() { findmnt -rno SOURCE "/var/lib/machines/$1" >/dev/null 2>&1; }

offline() {
  local n=${1:?이름} r=/var/lib/machines/$1 dev
  systemctl stop "guest@$n" 2>/dev/null || true
  mounted "$n" && return 0
  modprobe nbd max_part=16
  for dev in /dev/nbd{0..15}; do [ "$(cat /sys/block/${dev#/dev/}/size)" = 0 ] && break; done
  qemu-nbd -c "$dev" "$LIB/$n.qcow2"; echo "$dev" > "/run/guest-$n.nbd"
  for _ in $(seq 20); do [ -b "${dev}p1" ] && break; sleep 0.3; done
  install -d "$r"; mount "${dev}p1" "$r"
  mount "${dev}p16" "$r/boot"; mount "${dev}p15" "$r/boot/efi"
  echo "$n: $r 에 마운트($dev)"
}

umount_disk() {
  local n=${1:?이름} r=/var/lib/machines/$1
  mounted "$n" || return 0
  sync; umount "$r/boot/efi" "$r/boot" "$r"
  qemu-nbd -d "$(cat "/run/guest-$n.nbd")"; rm -f "/run/guest-$n.nbd"
}

online() {
  local n=${1:?이름}
  umount_disk "$n"
  systemctl enable -q "guest@$n"; systemctl start "guest@$n"
  echo "$n 시작"
}

seal_userdata() {  # 마운트된 상태에서: seed와 게스트에 저장된 user-data 사본을 기본형으로(빌드 묶음·runcmd 제거, instance-id 유지 → cloud-init 다시 안 돎)
  local n=${1:?이름} r=/var/lib/machines/$1 f
  seed "$n" 0
  for f in "$r"/var/lib/cloud/instances/*/user-data.txt "$r"/var/lib/cloud/instance/user-data.txt; do
    [ -f "$f" ] && cp "$LIB/$n-user-data.last" "$f"
  done
  rm -f "$r"/var/lib/cloud/instances/*/user-data.txt.i
}

hostkey() {  # 실행 중인 VM의 ed25519 호스트 공개키(다른 디코이의 known_hosts용). 디스크를 읽기 전용·공유로 잠깐 연다(VM은 그대로)
  local n=${1:?이름} dev m
  modprobe nbd max_part=16
  for dev in /dev/nbd{0..15}; do [ "$(cat /sys/block/${dev#/dev/}/size)" = 0 ] && break; done
  qemu-nbd -r --force-share -c "$dev" "$LIB/$n.qcow2"
  for _ in $(seq 20); do [ -b "${dev}p1" ] && break; sleep 0.3; done
  m=$(mktemp -d); mount -o ro,noload "${dev}p1" "$m"
  echo "hostkey=$(awk '{print $2}' "$m/etc/ssh/ssh_host_ed25519_key.pub")"
  umount "$m"; rmdir "$m"; qemu-nbd -d "$dev" >/dev/null
}

case "${1:-}" in
  hostkey) hostkey "${2:?}" ;;
  create) shift; create "$@" ;;
  offline) offline "${2:?}" ;;
  online) online "${2:?}" ;;
  seal) seal_userdata "${2:?}" ;;
  status) for e in "$ETC"/*.env; do [ -f "$e" ] || continue; n=$(basename "$e" .env); printf '%-12s %s\n' "$n" "$(systemctl is-active "guest@$n")"; done ;;
  *) sed -n '2,16p' "$0"; exit 2 ;;
esac
