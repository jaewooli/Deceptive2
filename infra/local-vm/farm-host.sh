#!/usr/bin/env bash
# 로컬 팜 = WSL2 자신(AWS 팜과 같은 구조: 한 OS가 KVM + 터널·라우팅, docs/local-aws-parity.md). 사용자 작업 환경이므로 docs/local-farm-recovery.md의 약속대로:
#   부팅 자동 시작 없음(wsl --shutdown = 완전 복구), 팜이 만든 것만 지움, eth0·기본 경로·기본 규칙은 안 건드림, 올리기 전 상태를 기준선으로 저장
#   infra/local-vm/farm-host.sh up      # 패키지·모듈 확인 → 기준선 저장 → relay 터널(센서 쪽도 새 키로) → 있던 트랩·디코이 다시 켬
#   infra/local-vm/farm-host.sh down    # 디코이·트랩 정지 → 터널·규칙·경로·nft·TTL·Docker 허용 줄 제거 → sysctl 기준선으로
#   infra/local-vm/farm-host.sh check   # 경로 단언 + 공격자 시점 + 안쪽 + 로컬 장치 검사
#   infra/local-vm/farm-host.sh status
# 트랩·투영 디코이를 새로 두거나 치우는 건 미끼 엔진(baits/engine.py apply·recall·feature)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
LAB="$ROOT/infra/local-vm/lab.sh"
CTL=${CTL_PY:-$HOME/.cache/deceptive2-ctl/bin/python}
BASE="$ROOT/out/local-farm"
sudo -n true 2>/dev/null || { echo "sudo(비밀번호 없음)가 필요 — docs/local-farm-recovery.md" >&2; exit 2; }

snapshot() {  # 비교·복구용 상태 기록(파일은 저장소 밖 out/)
  install -d "$BASE"
  { echo "# $(date -Is) $1"; ip -br link; echo; ip rule; echo; ip route show table all | grep -v '^local\|^broadcast\|^multicast'; echo
    sysctl net.ipv4.ip_forward net.ipv4.conf.all.rp_filter net.ipv4.conf.all.arp_ignore net.ipv4.conf.all.proxy_arp; echo
    sudo iptables-save 2>/dev/null || echo "(iptables 없음)"; echo; sudo nft list ruleset 2>/dev/null || echo "(nft 없음)"; } > "$BASE/$1-$(date +%Y%m%dT%H%M%S).txt"
}

up() {
  # 1. 필요한 도구(설치만 — 데이터는 안 건드림). nftables 부팅 서비스는 켜지 않는다(켜지면 부팅 때 규칙을 전부 비움 — Docker 규칙 포함)
  local need=() p nft_was
  nft_was=$(systemctl is-enabled nftables 2>/dev/null || echo missing)
  for p in wireguard-tools iptables nftables systemd-container qemu-utils qemu-system-x86; do [ "$(dpkg-query -W -f='${db:Status-Status}' "$p" 2>/dev/null)" = installed ] || need+=("$p"); done   # "deinstall(설정만 남음)"은 미설치
  if [ ${#need[@]} -gt 0 ]; then echo "설치: ${need[*]}"; sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends "${need[@]}" >/dev/null; fi
  [ "$nft_was" != enabled ] && sudo systemctl disable nftables >/dev/null 2>&1 || true
  sudo modprobe -a nbd wireguard tun xt_HL   # TTL 타깃은 xt_HL 모듈(CONFIG_NETFILTER_XT_TARGET_HL)
  # 2. farm VM(예전 팜)이 켜져 있으면 같은 UDP 포트(51820)를 잡고 있다
  if pgrep -f 'qemu-system.*lt-farm' >/dev/null; then echo "farm VM(lt-farm)이 켜져 있음 — lab.sh down farm 먼저" >&2; exit 2; fi
  # 3. 기준선(팜 것이 하나도 없을 때만 — 처음 상태를 남긴다)
  ip link show relay >/dev/null 2>&1 || snapshot baseline
  # 4. 환경 프로필 → 엔진 입력
  "$CTL" "$ROOT/infra/env/render.py" local
  # 5. relay 터널: 팜(WSL2) 쪽 → 공개키로 센서 쪽(엔드포인트 = VM에서 본 WSL2)
  local spub fpub ep
  spub=$("$LAB" ssh sensor 'sudo cat /etc/wireguard/relay.key 2>/dev/null | wg pubkey')
  [ -n "$spub" ] || { echo "센서 키 없음 — 센서에 install.sh tunnel 먼저" >&2; exit 2; }
  fpub=$(cd "$ROOT/servers/hosts/farm" && sudo PERSIST=false bash ./install.sh "$spub" | sed -n 's/^relay_public_key=//p')
  ep=$("$CTL" -c "import yaml; print(yaml.safe_load(open('$ROOT/infra/env/local.yml'))['farm']['tunnel_endpoint'])")
  "$LAB" run sensor "$ROOT/servers/hosts/sensor" install.sh tunnel "$ep:51820" "$fpub" | tail -1
  # 6. 레지스트리에서 active인 트랩·디코이만 다시 켠다(기능을 꺼 둔 paused는 그대로) — 새로 두는 건 엔진 apply
  local u
  for u in $("$CTL" - "$ROOT/out/baits/registry.json" <<'PY'
import json, sys
try:
    r = json.load(open(sys.argv[1]))
except OSError:
    sys.exit()
for p in r["placements"].values():
    if p["status"] != "active":
        continue
    if p["type"] == "decoy_port" and p.get("farm_slot"):
        print(f"wg-quick@edh{p['farm_slot']}", f"systemd-nspawn@trap-{p['host']}")
    if p["type"] == "projection":
        print(f"guest@{p['anchor']['name']}")
PY
); do
    sudo systemctl start "$u" || echo "시작 실패: $u"
  done
  echo "팜(WSL2) 올림 — 확인: infra/local-vm/farm-host.sh check"
}

down() {
  local i u p t
  for u in $(systemctl list-units --no-legend --plain 'guest@*' 'systemd-nspawn@trap-*' 'wg-quick@*' 2>/dev/null | awk '{print $1}'); do
    sudo systemctl stop "$u" 2>/dev/null || true
  done
  for i in $(ip -o link | awk -F': ' '{print $2}' | cut -d@ -f1 | grep -E '^(relay|edh[0-9]+|ve-)'); do sudo ip link del "$i" 2>/dev/null || true; done
  ip rule | awk -F: '($1>=49 && $1<=63) || ($1>=161 && $1<=199) {print $1}' | sort -u | while read -r p; do
    while sudo ip rule del pref "$p" 2>/dev/null; do :; done
  done
  for t in 110 111 112 113 120 141 142 143 191 192 193; do sudo ip route flush table "$t" 2>/dev/null || true; done
  for t in $(sudo nft list tables 2>/dev/null | awk '$2=="ip" && $3 ~ /^(guest_build|edh_[0-9]+|trap_[0-9]+)$/ {print $3}'); do sudo nft delete table ip "$t"; done
  sudo iptables -w -t mangle -S PREROUTING 2>/dev/null | grep -E -- '-j TTL --ttl-inc 1' | sed 's/^-A/-D/' | while read -r r; do eval "sudo iptables -w -t mangle $r"; done
  sudo iptables -w -S DOCKER-USER 2>/dev/null | grep -E -- '-[io] (relay|ve-\+|edh\+) -j ACCEPT' | sed 's/^-A/-D/' | while read -r r; do eval "sudo iptables -w $r"; done
  for m in $(findmnt -rno TARGET | grep '^/var/lib/machines/' || true); do sudo umount -R "$m" 2>/dev/null || true; done
  for d in /dev/nbd*; do [ -b "$d" ] && sudo qemu-nbd -d "$d" >/dev/null 2>&1 || true; done
  # sysctl → 기준선(처음 저장한 값, 없으면 11/23 문서 값)
  local b; b=$(ls "$BASE"/baseline-*.txt 2>/dev/null | head -1 || true)
  local fwd=0 ign=0 rpf=2
  if [ -n "$b" ]; then
    fwd=$(sed -n 's/^net.ipv4.ip_forward = //p' "$b"); ign=$(sed -n 's/^net.ipv4.conf.all.arp_ignore = //p' "$b"); rpf=$(sed -n 's/^net.ipv4.conf.all.rp_filter = //p' "$b")
  fi
  sudo sysctl -q -w net.ipv4.ip_forward="$fwd" net.ipv4.conf.all.arp_ignore="$ign" net.ipv4.conf.all.rp_filter="$rpf"
  snapshot after-down
  echo "팜(WSL2) 내림 — 남은 것 비교: diff $b $(ls -t "$BASE"/after-down-*.txt | head -1)"
}

check() {
  local s rc=0
  for s in paths attacker inside lab features; do echo "== $s"; "$CTL" "$ROOT/infra/checks/paths.py" "$ROOT/infra/checks/$s.spec" || rc=1; done
  return $rc
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  check) check ;;
  status) ip -br link | grep -E '^(relay|edh|ve-)' || echo "팜 인터페이스 없음"; systemctl list-units --no-legend --plain 'guest@*' 'systemd-nspawn@trap-*' 'wg-quick@*' 2>/dev/null ;;
  *) sed -n '2,8p' "$0"; exit 2 ;;
esac
