#!/usr/bin/env bash
# sensor — 투영 센서(벤더 투영의 센서 쪽, docs/01-vendor-feature-map.md 문제 2). root로, 여러 번 실행해도 결과가 같다.
#   sudo ./install.sh tunnel <팜 엔드포인트 host:port> <팜 공개키>        # 팜과의 터널(relay). 공개키를 출력
#   sudo ./install.sh add <투영 NIC> <투영 주소/접두> <게이트웨이|->       # 투영 하나 추가(디코이 하나 = NIC 하나, HANDOFF 9절 MAC 묶임)
#   sudo ./install.sh remove <투영 주소>                                     # 흔적 없이 빼기
#   예) 로컬: add enp0s3 10.0.20.16/24 10.0.20.1     add enp0s8 10.0.21.12/24 10.0.21.1     EC2: add ens6 10.0.2.40/24 10.0.2.1
# 하는 일(투영마다)
#   - 투영 주소로 들어온 패킷을 로컬로 받지 않고 WireGuard로 팜에 넘긴다(출발지 주소 그대로 — NAT 없음, 경보·디코이가 진짜 출발지를 봄)
#   - 팜 디코이의 응답(출발지 = 투영 주소)을 그 투영 NIC로 내보낸다(구간마다 경로표 하나)
#   - 센서 자신은 투영 주소에서 아무 서비스도 열지 않는다(관리 NIC만, EC2는 SSM)
# 투영 목록: /etc/relay/projections("NIC 주소/접두 게이트웨이 경로표" 한 줄씩). 터널 PostUp이 이 목록대로 다시 건다(재부팅·터널 재시작)
# 키: 처음 실행 때 /etc/wireguard/relay.key를 만든다(저장소에 넣지 않음)
set -euo pipefail
LIST=/etc/relay/projections
UP=/usr/local/lib/relay/projections-up
export DEBIAN_FRONTEND=noninteractive

common() {
  command -v wg >/dev/null || apt-get install -y -q wireguard-tools
  install -d -m 0700 /etc/wireguard; install -d /etc/relay /usr/local/lib/relay; touch "$LIST"
  [ -f /etc/wireguard/relay.key ] || (umask 077; wg genkey > /etc/wireguard/relay.key)
  cat > /etc/sysctl.d/60-relay.conf <<EOF
net.ipv4.ip_forward = 1
net.ipv4.conf.all.rp_filter = 2
EOF
  sysctl -q -p /etc/sysctl.d/60-relay.conf
  rm -f /etc/netplan/60-relay.yaml   # 11/23까지의 단일 투영 설정(이제 NIC마다 60-relay-<NIC>.yaml)
  # networkd가 자기가 만들지 않은 규칙·경로를 지우지 않게(아래 응답 규칙)
  install -d /etc/systemd/networkd.conf.d
  printf '[Network]\nManageForeignRoutingPolicyRules=no\nManageForeignRoutes=no\n' > /etc/systemd/networkd.conf.d/10-keep-foreign.conf
  # 투영 목록대로 경로·규칙·TTL 보정을 건다(터널 PostUp·add가 부름). 규칙 아닌 main /32 경로 → 지워져도 센서는 멀쩡(11/22 먹통 교훈)
  cat > "$UP" <<'EOF'
#!/bin/sh
# 투영 주소 → 터널(main /32), 팜에서 돌아온 응답(출발지 = 투영 주소) → 그 투영 NIC의 경로표
# 포워딩 홉마다 TTL이 1 준다 → 투영 디코이가 같은 서브넷인데 TTL 62로 보임(11/23 실측). 들어올 때 1을 되돌린다(양방향)
ipt() { iptables -w -t mangle -C PREROUTING "$@" 2>/dev/null || iptables -w -t mangle -A PREROUTING "$@"; }
[ -e /sys/class/net/relay ] || exit 0
ipt -i relay -j TTL --ttl-inc 1
while read -r ifc addr gw table; do
  [ -n "$ifc" ] || continue
  x=${addr%/*}
  ip route replace "$x/32" dev relay
  ip rule show from "$x" iif relay | grep -q "lookup $table" || ip rule add pref 51 iif relay from "$x/32" lookup "$table"
  net=$(python3 -c "import ipaddress,sys; print(ipaddress.ip_interface(sys.argv[1]).network)" "$addr")
  ip route replace "$net" dev "$ifc" table "$table"
  if [ "$gw" = "-" ]; then ip route replace default dev "$ifc" table "$table"; else ip route replace default via "$gw" dev "$ifc" onlink table "$table"; fi
  ipt -i "$ifc" -d "$x/32" -j TTL --ttl-inc 1
done < /etc/relay/projections
exit 0
EOF
  chmod 755 "$UP"
}

nic() {  # 투영 NIC: 투영 주소를 센서 자신의 주소로 두지 않는다(자기 주소면 local 규칙을 옮겨야 하고, networkd가 지우면 센서 전체가 먹통 — 11/22)
  # AWS: VPC가 ENI 주소로 온 패킷을 ENI로 넘겨준다(OS 설정 불필요). 로컬 L2: proxy ARP가 대신 답한다(경로가 다른 NIC라서) — 그러려면 NIC에 IPv4가 하나 필요(링크 로컬)
  local ifc=$1
  cat > "/etc/netplan/60-relay-$ifc.yaml" <<EOF
network:
  version: 2
  ethernets:
    $ifc:
      dhcp4: false
      dhcp6: false
      accept-ra: false
      link-local: []
      addresses: [169.254.31.1/32]
EOF
  chmod 600 "/etc/netplan/60-relay-$ifc.yaml"
  printf 'net.ipv4.conf.%s.rp_filter = 2\nnet.ipv4.conf.%s.proxy_arp = 1\n' "$ifc" "$ifc" > "/etc/sysctl.d/61-relay-$ifc.conf"
  sysctl -q -p "/etc/sysctl.d/61-relay-$ifc.conf"
  netplan apply
}

allowed() {  # 터널 AllowedIPs = 팜 터널 주소 + 모든 투영 주소
  local a="10.200.0.2/32" x
  for x in $(awk '{print $2}' "$LIST"); do a+=", ${x%/*}/32"; done
  sed -i "s|^AllowedIPs = .*|AllowedIPs = $a|" /etc/wireguard/relay.conf
  wg set relay peer "$(sed -n 's/^PublicKey = //p' /etc/wireguard/relay.conf)" allowed-ips "${a//, /,}" 2>/dev/null || true
}

case "${1:-}" in
  tunnel)
    FARM=${2:?팜 엔드포인트}; FARM_PUB=${3:?팜 공개키}; common
    cat > /etc/wireguard/relay.conf <<EOF
[Interface]
PrivateKey = $(cat /etc/wireguard/relay.key)
Address = 10.200.0.1/30
Table = off
# MTU = 구간(LAN·VPC) MTU 그대로(로컬 1500, AWS 9001). 바깥 UDP는 IP 단편화에 맡긴다(WireGuard는 바깥 패킷에 DF를 안 건다).
# 11/23 실측: 1380 + MSS 조정이면 공격자 SYN-ACK에 MSS 1340(이웃은 1460)·DF 1472 ping 소실·tracepath 무응답 → 디코이가 터널 뒤임이 드러남
MTU = $(cat /sys/class/net/"$(ip -o route get 1.1.1.1 | sed -n 's/.* dev \([^ ]*\).*/\1/p')"/mtu)
PostUp = $UP
PreDown = while ip rule del pref 51 2>/dev/null; do :; done

[Peer]
PublicKey = $FARM_PUB
Endpoint = $FARM
AllowedIPs = 10.200.0.2/32
PersistentKeepalive = 25
EOF
    chmod 600 /etc/wireguard/relay.conf
    allowed
    systemctl enable wg-quick@relay >/dev/null 2>&1
    systemctl restart wg-quick@relay
    echo "relay_public_key=$(wg pubkey < /etc/wireguard/relay.key)" ;;
  add)
    IF=${2:?투영 NIC}; ADDR=${3:?투영 주소/접두}; GW=${4:?게이트웨이 또는 -}; common
    grep -q " ${ADDR%/*}/" "$LIST" 2>/dev/null && sed -i "\| ${ADDR%/*}/|d" "$LIST"
    if awk -v i="$IF" '$1==i' "$LIST" | grep -q .; then echo "$IF에 이미 투영이 있음(디코이 하나 = NIC 하나)" >&2; exit 2; fi
    T=$(awk 'BEGIN{t=110} {if ($4>=t) t=$4} END{print t+1}' "$LIST")
    echo "$IF $ADDR $GW $T" >> "$LIST"
    nic "$IF"; allowed; "$UP"
    echo "projection ${ADDR%/*} → relay(NIC $IF, MAC $(cat /sys/class/net/$IF/address), table $T)"
    echo "projection_mac=$(cat /sys/class/net/$IF/address)" ;;
  remove)
    X=${2:?투영 주소}; X=${X%/*}
    read -r IF ADDR GW T < <(awk -v x="$X" 'index($2, x"/")==1' "$LIST") || { echo "없음: $X"; exit 0; }
    ip route del "$X/32" dev relay 2>/dev/null || true
    ip rule del pref 51 iif relay from "$X/32" lookup "$T" 2>/dev/null || true
    ip route flush table "$T" 2>/dev/null || true
    iptables -w -t mangle -D PREROUTING -i "$IF" -d "$X/32" -j TTL --ttl-inc 1 2>/dev/null || true
    sed -i "\| $X/|d" "$LIST"; allowed
    rm -f "/etc/netplan/60-relay-$IF.yaml" "/etc/sysctl.d/61-relay-$IF.conf"; netplan apply
    echo "removed $X" ;;
  *) sed -n '2,14p' "$0"; exit 2 ;;
esac
