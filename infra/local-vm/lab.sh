#!/usr/bin/env bash
# 로컬 랩 전체를 한 표로 다룬다(11/22 — 매번 긴 환경 변수를 손으로 쳐서 틀리던 것). 서버 역할 이름으로 부른다.
#   infra/local-vm/lab.sh up [역할...|all]      # 호스트 서비스(apt 캐시·파일 배포) + VM 켜기 + 공유 LAN 주소 확인
#   infra/local-vm/lab.sh down [역할...|all]
#   infra/local-vm/lab.sh status
#   infra/local-vm/lab.sh ssh <역할> [명령]
#   infra/local-vm/lab.sh run <역할> <로컬 디렉터리> <그 안의 스크립트> [인자...]   # 임시 경로에 풀고 sudo bash 실행 → 지움
#   infra/local-vm/lab.sh mem                    # 호스트에서 본 VM별 메모리
# 공유 LAN = QEMU 멀티캐스트(10.0.20.0/24, VPC 서브넷 대신). VM 안의 apt 프록시 설정은 로컬 전용(AWS엔 없음)
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
VM="$HERE/vm.sh"
DIR=${VM_DIR:-$HOME/.cache/deceptive2-vm}
# 공유 LAN 2개 = VPC 서브넷 2개(11/23 구간 분리). 서브넷 사이는 router VM이 .1로 잇는다(VPC 라우터 역할, 로컬 전용)
#   int = internal 10.0.20.0/24(AWS 10.0.2.0/24), pub = public 10.0.21.0/24(AWS 10.0.1.0/24)
declare -A LANS=([int]="mcast=239.192.20.1:10100,localaddr=127.0.0.1" [pub]="mcast=239.192.21.1:10101,localaddr=127.0.0.1")
declare -A LANGW=([int]=10.0.20.1 [pub]=10.0.21.1)
declare -A LANOCT=([int]=20 [pub]=21)
APT_PORT=3142
FILES_PORT=8098

# 역할      VM 이름     ssh   pg     seed  메모리  LAN  MAC 끝  LAN 주소      추가 NIC(LAN:MAC 끝,…)  추가 포워딩
# 메모리: 게스트 실사용(400~540MB) + 여유. 합계를 호스트(7.9GB)의 약 55%로 — 넘기면 호스트 스왑이 차서 VM이 응답을 못 함(11/22)
#   farm은 디코이 KVM VM(stg-01 768 + dev-01)을 품어 2304. 전부 켜면 55%를 넘는다 → 작업에 필요 없는 VM은 끈다(lab.sh mem으로 확인)
#   ClamAV 전체 검사(약 1GB)를 돌릴 때만 그 VM을 VM_MEM=2048로 따로 켠다
# 센서 NIC: 투영 디코이마다 하나(그 NIC MAC = 디코이 NIC MAC, HANDOFF 9절). enp0s3 = int, enp0s8 = pub
TABLE="
router       lt-router  2236  15436  8096  384     int  01      10.0.20.1     pub:01                  -
app-01       lt-app     2232  15432  8092  896     int  10      10.0.20.10    -                       -
web-01       web-01     2235  15435  8095  1024    pub  11      10.0.21.11    -                       -
db-backup-01 lt-decoy   2231  15431  8091  768     int  15      10.0.20.15    -                       -
farm         lt-farm    2234  15434  8094  2304    int  40      10.0.20.40    -                       hostfwd=udp:127.0.0.1:51820-:51820
sensor       lt-sensor  2233  15433  8093  512     int  30      -             pub:30                  -
"

row() { awk -v r="$1" '$1==r' <<<"$TABLE"; }
roles() { awk 'NF {print $1}' <<<"$TABLE"; }
pick() { if [ "${1:-all}" = all ]; then roles; else printf '%s\n' "$@"; fi; }
env_for() {
  read -r role name ssh pg seed mem lan mac ip nics extra <<<"$(row "$1")"
  [ -n "${name:-}" ] || { echo "모르는 역할: $1" >&2; exit 2; }
  export VM_NAME=$name VM_SSH_PORT=$ssh VM_PG_PORT=$pg VM_SEED_PORT=$seed VM_MEM=$mem
  export VM_LAN_TYPE=socket VM_LAN=${LANS[$lan]} VM_LAN_MAC=52:54:00:${LANOCT[$lan]}:00:$mac
  VM_LAN_EXTRA=""
  if [ "$nics" != "-" ]; then
    local e; for e in ${nics//,/ }; do VM_LAN_EXTRA+="${LANS[${e%%:*}]}@52:54:00:${LANOCT[${e%%:*}]}:00:${e#*:} "; done
  fi
  export VM_LAN_EXTRA
  if [ "$extra" != "-" ]; then export VM_EXTRA_FWD=$extra; else unset VM_EXTRA_FWD; fi
  # farm은 디코이 VM을 품는다(3중 중첩): vCPU 4, 디코이는 1(2면 게스트 메모리 손상 — 11/23 Oops·soft lockup, destinations farm.guest_cpus)
  if [ "$role" = farm ]; then export VM_CPUS=4; else unset VM_CPUS; fi
  LAN_IP=$ip; LAN_GW=${LANGW[$lan]}; ROLE=$role
}

host_services() {
  if ! (exec 3<>/dev/tcp/127.0.0.1/$APT_PORT) 2>/dev/null; then
    nohup python3 "$HERE/apt_cache.py" $APT_PORT >"$DIR/apt-cache.log" 2>&1 &
  fi
  if ! (exec 3<>/dev/tcp/127.0.0.1/$FILES_PORT) 2>/dev/null; then
    install -d "$DIR/files"
    nohup python3 -m http.server $FILES_PORT --bind 127.0.0.1 --directory "$DIR/files" >"$DIR/files-http.log" 2>&1 &
  fi
}

lan_and_proxy() {  # 부팅 뒤: 공유 LAN 주소 + 다른 서브넷으로 가는 경로(.1 = router), 로컬 전용 apt 프록시
  # 첫 LAN NIC = enp0s3(관리 NIC enp0s2 다음 슬롯). 추가 NIC(enp0s8~)는 역할 스크립트가 설정(router.sh·센서 install.sh)
  local ip=$1 gw=$2 role=$3 route=""
  [ "$role" != router ] && route="\n      routes:\n        - to: 10.0.0.0/16\n          via: $gw"
  "$VM" ssh "sudo sh -s" <<EOF
printf 'Acquire::http::Proxy "http://10.0.2.2:$APT_PORT";\n' > /etc/apt/apt.conf.d/01-lab-proxy
if [ "$ip" != "-" ]; then
  printf "network:\n  version: 2\n  ethernets:\n    enp0s3:\n      dhcp4: false\n      addresses: [$ip/24]$route\n" > /tmp/60-lan.yaml
  if ! cmp -s /tmp/60-lan.yaml /etc/netplan/60-lan.yaml; then
    install -m 600 /tmp/60-lan.yaml /etc/netplan/60-lan.yaml; netplan apply
  fi
  rm -f /tmp/60-lan.yaml
fi
EOF
}

case "${1:-}" in
  up)
    shift; host_services
    for r in $(pick "$@"); do env_for "$r"; echo "== $r ($VM_NAME, ${VM_MEM}MB)"; "$VM" up | tail -1; lan_and_proxy "$LAN_IP" "$LAN_GW" "$ROLE"; done ;;
  down)
    shift; for r in $(pick "$@"); do env_for "$r"; "$VM" down; echo "$r 꺼짐"; done ;;
  status)
    for r in $(roles); do env_for "$r"
      if [ -f "$DIR/$VM_NAME.pid" ] && kill -0 "$(cat "$DIR/$VM_NAME.pid")" 2>/dev/null; then st=켜짐; else st=꺼짐; fi
      printf '%-13s %-10s %s ssh:%s lan:%s\n' "$r" "$VM_NAME" "$st" "$VM_SSH_PORT" "$LAN_IP"; done ;;
  ssh)
    env_for "${2:?역할}"; shift 2; exec "$VM" ssh "$@" ;;
  run)
    env_for "${2:?역할}"; d=${3:?디렉터리}; sc=${4:?스크립트}; shift 4
    tar -C "$d" -czf - . | "$VM" ssh "t=\$(mktemp -d); tar -C \$t -xzf -; sudo bash \$t/$sc $(printf '%q ' "$@"); rc=\$?; sudo rm -rf \$t; exit \$rc" ;;
  mem)
    for r in $(roles); do env_for "$r"
      [ -f "$DIR/$VM_NAME.pid" ] && p=$(cat "$DIR/$VM_NAME.pid") && kill -0 "$p" 2>/dev/null &&
        printf '%-13s 할당 %5sMB  호스트 RSS %5dMB\n' "$r" "$VM_MEM" "$(($(ps -o rss= -p "$p") / 1024))"; done
    free -m | awk '/Mem:/{print "호스트 가용 " $7 "MB / " $2 "MB"}' ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
