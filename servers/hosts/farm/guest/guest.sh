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
# 네트워크: VM NIC = 탭 ve-<이름>(relay 규칙 그대로), PCI 슬롯 3 → 게스트 enp0s3. 탭 설정은 guest-up이(networkd엔 Unmanaged만 —
#   WSL2 팜은 networkd가 안 돌고, AWS 팜은 돌아도 이 링크를 안 잡게: 같은 코드)
# 환경 값(기본값 없음 — infra/env/<환경>.yml → 미끼 엔진이 넘김, docs/local-aws-parity.md):
#   GUEST_HW(local|aws) DISK_GB GUEST_DNS APT_PROXY(빈 값 가능) CWAGENT_MODE PERSIST(true|false) BUILD_REDIRECT("proto:주소:포트>대상;…", 빈 값 가능)
# GUEST_HW=local: 로컬 랩 VM과 같은 모양(q35·virtio·balloon·cloud-id nocloud). aws(EC2 모양·IMDS)는 미구현 — local-aws-parity 4절
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
LIB=/var/lib/guests; ETC=/etc/guest; LOGD=/var/log/guests
BASE_IMG=/var/cache/decoy/noble-server-cloudimg-amd64.img
IMG_URL=https://cloud-images.ubuntu.com/noble/current
envs() {  # create 때 환경 값 확인(이후 offline·seal·online은 <이름>.env에서 읽음)
  : "${GUEST_HW:?GUEST_HW}" "${DISK_GB:?DISK_GB}" "${GUEST_DNS:?GUEST_DNS}" "${CWAGENT_MODE:?CWAGENT_MODE}" "${PERSIST:?PERSIST}"
  APT_PROXY=${APT_PROXY-}; BUILD_REDIRECT=${BUILD_REDIRECT-}
  [ "$GUEST_HW" = local ] || { echo "GUEST_HW=$GUEST_HW 미구현(EC2 모양·IMDS — docs/local-aws-parity.md 4절)" >&2; exit 2; }
}
export DEBIAN_FRONTEND=noninteractive

need() {
  dpkg -s qemu-system-x86 qemu-utils >/dev/null 2>&1 ||
    apt-get install -y -q --no-install-recommends qemu-system-x86 qemu-utils >/dev/null
  install -d -m 0700 "$LIB" "$ETC"; install -d "$LOGD" /usr/local/lib/relay
  if [ -n "${BASE_IMAGE:-}" ]; then   # 환경 프로필 guest.base_image: 이웃과 같은 serial의 이미지(경로 또는 URL)
    BASE_IMG=$LIB/base-$(basename "$BASE_IMAGE")
    if [ ! -f "$BASE_IMG" ]; then
      case $BASE_IMAGE in http*) curl -fsSL -o "$BASE_IMG" "$BASE_IMAGE" ;; *) cp "$BASE_IMAGE" "$BASE_IMG" ;; esac
    fi
  elif [ ! -f "$BASE_IMG" ]; then
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
      addresses: [$GUEST_DNS]
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
    # 진짜 서버가 밟은 순서를 그대로(11/23 실측, 이웃 apt 기록): 이미지(같은 serial) → cloud-init이 저장소 파일 생성 → 역할 패키지 apt-get install
    # → 공통 베이스(lab.sh run처럼 /tmp/tmp.XXXX에서) → unattended-upgrade(보안만 — 이웃의 커널 149가 이 경로로 들어옴). full-upgrade는 안 함
    # 패치 시점 = 이웃과 같은 아카이브 스냅숏(일반: 이웃의 마지막 apt 작업, 보안: 마지막 unattended-upgrade). 저장소 파일엔 빌드 동안만 넣는다
    # (스냅숏 주소는 apt가 Release의 Origin으로 찾음 — apt.conf(5) Snapshots::URI, security 단락도 됨: 11/23 로그 확인)
    # 빌드 재료는 /var/tmp/.b(/run은 noexec — 11/23), 결과 표시 /var/tmp/.b.ok는 팜이 꺼진 디스크에서 읽고 seal이 지운다
    local B=/var/tmp/.b
    cat > "$d/build.sh" <<BUILD
#!/bin/sh
set -e
export DEBIAN_FRONTEND=noninteractive
S=/etc/apt/sources.list.d/ubuntu.sources
cp -p "\$S" $B/sources.gen
if [ -n "${SNAPSHOT:-}" ]; then
  awk -v m="${SNAPSHOT:-}" -v s="${SNAPSHOT_SECURITY:-${SNAPSHOT:-}}" 'BEGIN{RS="";ORS="\\n\\n"} /(^|\\n)Types:/ {print \$0 "\\nSnapshot: " (index(\$0,"-security")?s:m); next} {print}' $B/sources.gen > "\$S"
  printf 'Acquire::https::Proxy "DIRECT";\\n' > /etc/apt/apt.conf.d/50-build-snapshot   # 스냅숏은 https — http 전용 로컬 프록시를 안 거치게
fi
apt-get update -q
apt-get install -y -q ${PKGS//,/ }
[ ! -f $B/mirror.tgz ] || tar -C / -xpzf $B/mirror.tgz
t=\$(mktemp -d)
tar -C "\$t" --no-same-owner -xzf $B/base.tgz
cd "\$t"
CWAGENT_MODE=$CWAGENT_MODE ./install.sh${PG:+
./install.sh postgresql}
cd /
rm -rf "\$t"
# 이웃이 밟은 순서대로: 직접 업그레이드(before = unattended보다 먼저) → unattended-upgrade → 직접 업그레이드(after)
${MANUAL_UPGRADE:+[ "$MANUAL_UPGRADE" != before ] || apt-get -y -q full-upgrade}
unattended-upgrade
${MANUAL_UPGRADE:+[ "$MANUAL_UPGRADE" != after ] || apt-get -y -q full-upgrade}
touch $B.ok
BUILD
    local proxy=""   # 로컬 진짜 VM과 같은 파일(lab.sh lan_and_proxy). ${..:+..} 안에 쓰면 따옴표가 빠져 apt 구문 오류(11/23)
    [ -n "$APT_PROXY" ] && proxy="  - path: /etc/apt/apt.conf.d/01-lab-proxy"$'\n'"    content: |"$'\n'"      Acquire::http::Proxy \"$APT_PROXY\";"$'\n'
    local mirror=""   # 진짜 서버에서 그대로 복사한 로컬 전용 파일(환경 프로필 guest.mirror_files)
    [ -f "$HERE/mirror.tgz" ] && mirror="  - path: $B/mirror.tgz"$'\n'"    encoding: b64"$'\n'"    content: $(base64 -w0 < "$HERE/mirror.tgz")"$'\n'
    cat >> "$d/user-data" <<EOF
write_files:
${mirror}${proxy}  - path: $B/base.tgz
    encoding: b64
    content: $(tar -C "$HERE/base" -czf - . | base64 -w0)
  - path: $B/build.sh
    encoding: b64
    content: $(base64 -w0 < "$d/build.sh")
runcmd:
  - [sh, $B/build.sh]
  # 위가 실패해도 정리는 한다(runcmd는 set -e 없는 /bin/sh — cloud-init util.shellify): 저장소 파일을 cloud-init이 만든 원래대로, 빌드 재료 삭제
  - [sh, -c, "[ -f $B/sources.gen ] && cp -p $B/sources.gen /etc/apt/sources.list.d/ubuntu.sources; rm -f /etc/apt/apt.conf.d/50-build-snapshot; apt-get update -q >/dev/null 2>&1; rm -rf $B"]
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
  # BUILD_REDIRECT: 디코이가 본 주소(진짜 VM과 같은 apt 프록시·DNS) → 팜 쪽 실제 주소. via=resolver면 팜의 상위 DNS
  local pre="" r proto to port via
  # shellcheck disable=SC1090
  . "$ETC/$n.env"
  for r in ${BUILD_REDIRECT//;/ }; do
    proto=${r%%:*}; to=${r#*:}; to=${to%%:*}; port=${r#*:*:}; port=${port%%>*}; via=${r#*>}
    [ "$via" = resolver ] && via="$(awk '/^nameserver/ {print $2; exit}' /run/systemd/resolve/resolv.conf 2>/dev/null || true)"
    [ -n "$via" ] || via="$(awk '/^nameserver/ {print $2; exit}' /etc/resolv.conf)"
    case $via in *:*) ;; *) via="$via:$port" ;; esac
    pre+="iifname \"ve-$n\" ip daddr $to $proto dport $port dnat to $via; "
  done
  if [ "$1" = on ]; then
    ip rule show pref 49 | grep -q . || ip rule add pref 49 iif "ve-$n" lookup main
    # 127.0.0.1로 돌리려면 그 링크에서 루프백 목적지를 허용해야 한다(빌드 동안만). 탭은 VM이 뜰 때 생기므로 guest-up이 표시를 보고 켠다
    touch "/run/guest-$n.build"
    nft -f - <<EOF
table ip guest_build
delete table ip guest_build
table ip guest_build {
  chain pre { type nat hook prerouting priority dstnat; policy accept; $pre}
  chain post { type nat hook postrouting priority srcnat; policy accept; ip saddr $x oifname "$(uplink)" masquerade; }
}
EOF
  else
    ip rule del pref 49 2>/dev/null || true
    nft delete table ip guest_build 2>/dev/null || true
    rm -f "/run/guest-$n.build"; sysctl -q -w "net.ipv4.conf.ve-$n.route_localnet=0" 2>/dev/null || true
  fi
}

create() {
  local n=${1:?이름} addr=${2:?주소/접두} gw=${3:?게이트웨이} mac=${4:?MAC} mem=${5:?메모리} cpus=${6:?vCPU} pkgs=${7:?패키지} key=${8:?공개키} pg=${9:-}
  envs; need
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
SNAPSHOT_SECURITY=${APT_SNAPSHOT_SECURITY:-}
MANUAL_UPGRADE=${APT_MANUAL_UPGRADE:-}
INSTANCE_ID=$iid
GUEST_HW=$GUEST_HW
GUEST_DNS=$GUEST_DNS
APT_PROXY=$APT_PROXY
CWAGENT_MODE=$CWAGENT_MODE
PERSIST=$PERSIST
BUILD_REDIRECT="$BUILD_REDIRECT"
EOF
  install -m 0644 "$key" "$ETC/$n.pub"
  # 팜 쪽 탭: 설정은 guest-up(링크 로컬 + proxy ARP). networkd가 돌더라도 이 링크는 안 잡게(Unmanaged — 11/22 경쟁, WSL2엔 networkd 없음)
  # 게이트웨이(.1)를 팜 자신의 주소로 두지 않는다 — 두면 팜이 LAN에서 진짜 라우터(.1)의 ARP를 가로챈다(Linux는 어느 NIC로 온 ARP든
  # 자기 주소면 답함, 11/23 구간 분리 때 발견). 탭엔 링크 로컬만, 게이트웨이 ARP는 proxy ARP가 답한다(팜이 그 주소로 가는 경로를 LAN 쪽에 가짐)
  install -d /etc/systemd/network
  printf '[Match]\nName=ve-%s\n\n[Link]\nUnmanaged=yes\n' "$n" > "/etc/systemd/network/10-ve-$n.network"
  systemctl is-active -q systemd-networkd && networkctl reload 2>/dev/null || true
  systemctl stop "guest@$n" 2>/dev/null || true
  systemctl disable "systemd-nspawn@$n" 2>/dev/null || true; systemctl stop "systemd-nspawn@$n" 2>/dev/null || true
  rm -f "$LIB/$n.qcow2"
  qemu-img convert -q -O qcow2 "$BASE_IMG" "$LIB/$n.qcow2"
  qemu-img resize -q "$LIB/$n.qcow2" "${DISK_GB}G"   # 같은 환경의 진짜 서버 디스크 크기(로컬 vda 20G, EC2 8G)
  offline "$n"; seed "$n" 1; umount_disk "$n"
  build_egress on "$n"
  : > "$LOGD/$n.log"
  systemctl start "guest@$n"
  echo "1단계: $n 첫 부팅(cloud-init: 업그레이드·패키지·공통 베이스) — 끝나면 스스로 꺼짐"
  local t=0
  while systemctl is-active -q "guest@$n"; do sleep 10; t=$((t + 10)); [ $t -ge 2400 ] && { echo "시간 초과" >&2; break; }; done
  build_egress off "$n"
  grep -a "Cloud-init v.* finished" "$LOGD/$n.log" | tail -1 || true
  cp "$LOGD/$n.log" "$LOGD/$n-build.log"   # 다음 부팅이 콘솔 로그를 덮어쓰므로 빌드 기록을 따로 남김
  offline "$n" >/dev/null
  if [ -f "/var/lib/machines/$n/var/tmp/.b.ok" ]; then ok=1; else ok=0; fi
  umount_disk "$n"
  [ "$ok" = 1 ] || { echo "1단계 실패: 공통 베이스 설치가 끝나지 않음 — 게스트 /var/log/cloud-init-output.log, $LOGD/$n-build.log" >&2; exit 1; }
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
  # shellcheck disable=SC1090
  . "$ETC/$n.env"
  [ "$PERSIST" = true ] && systemctl enable -q "guest@$n"   # WSL2 팜은 부팅 자동 시작 없음(docs/local-farm-recovery.md)
  systemctl start "guest@$n"
  echo "$n 시작"
}

seal_userdata() {  # 마운트된 상태에서: seed와 게스트에 저장된 user-data 사본을 기본형으로(빌드 묶음·runcmd 제거, instance-id 유지 → cloud-init 다시 안 돎)
  local n=${1:?이름} r=/var/lib/machines/$1 f
  seed "$n" 0
  # instances/<id>/ 실제 파일만 — instance는 게스트 안 절대 경로 링크라 팜에서 따라가면 팜(WSL2) 자신의 /var/lib/cloud를 가리킨다(11/23)
  for f in "$r"/var/lib/cloud/instances/*/user-data.txt; do
    [ -f "$f" ] && [ ! -L "$f" ] && cp "$LIB/$n-user-data.last" "$f"
  done
  rm -f "$r"/var/lib/cloud/instances/*/user-data.txt.i
  # cloud-init은 부팅마다 캐시(obj.pkl)의 user-data로 user-data.txt를 다시 쓴다 → 캐시를 지워 seed(기본형)를 다시 읽게.
  # instance-id가 같아 "같은 인스턴스"로 보고 첫 부팅 모듈(호스트 키·사용자)은 다시 돌지 않는다
  rm -f "$r"/var/lib/cloud/instances/*/obj.pkl
  rm -f "$r/var/tmp/.b.ok"   # 1단계 결과 표시(create가 읽음)
}

hostkey() {  # 실행 중인 VM의 ed25519 호스트 공개키(다른 디코이의 known_hosts용). 디스크를 읽기 전용·공유로 잠깐 연다(VM은 그대로)
  local n=${1:?이름} dev m
  modprobe nbd max_part=16
  for dev in /dev/nbd{0..15}; do [ "$(cat /sys/block/${dev#/dev/}/size)" = 0 ] && break; done
  qemu-nbd -r -c "$dev" --image-opts "driver=qcow2,file.driver=file,file.filename=$LIB/$n.qcow2,file.locking=off"   # 실행 중 VM 디스크 잠금을 피해 읽기 전용으로
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
