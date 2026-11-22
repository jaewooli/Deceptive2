#!/usr/bin/env bash
# sensor — 투영 센서(벤더 투영의 센서 쪽, docs/01-vendor-feature-map.md 문제 2). root로, 여러 번 실행해도 결과가 같다.
#   sudo ./install.sh <투영 NIC> <투영 주소/접두> <투영 서브넷 게이트웨이|-> <팜 엔드포인트 host:port> <팜 공개키>
#   예) 로컬: ./install.sh enp0s3 10.0.20.30/24 - 10.0.2.2:51820 <키>   EC2: ./install.sh ens6 10.0.2.40/24 10.0.2.1 10.0.3.20:51820 <키>
# 하는 일
#   - 투영 주소로 들어온 패킷을 로컬로 받지 않고 WireGuard로 팜에 넘긴다(출발지 주소 그대로 — NAT 없음, 경보·디코이가 진짜 출발지를 봄)
#   - 팜 디코이의 응답(출발지 = 투영 주소)을 투영 NIC로 내보낸다
#   - 센서 자신은 투영 주소에서 아무 서비스도 열지 않는다(관리 NIC만, EC2는 SSM)
# 키: 처음 실행 때 /etc/wireguard/relay.key를 만들고 공개키를 출력한다(저장소에 넣지 않음)
set -euo pipefail
IF=${1:?투영 NIC}; ADDR=${2:?투영 주소/접두}; GW=${3:?게이트웨이 또는 -}; FARM=${4:?팜 엔드포인트}; FARM_PUB=${5:?팜 공개키}
X=${ADDR%/*}
T_IN=110; T_OUT=111
export DEBIAN_FRONTEND=noninteractive
command -v wg >/dev/null || apt-get install -y -q wireguard-tools

install -d -m 0700 /etc/wireguard
[ -f /etc/wireguard/relay.key ] || (umask 077; wg genkey > /etc/wireguard/relay.key)

# 투영 NIC: 투영 주소만, 기본 경로 없음(관리 NIC의 기본 경로를 건드리지 않게)
cat > /etc/netplan/60-relay.yaml <<EOF
network:
  version: 2
  ethernets:
    $IF:
      dhcp4: false
      dhcp6: false
      accept-ra: false
      addresses: [$ADDR]
EOF
chmod 600 /etc/netplan/60-relay.yaml
netplan apply

cat > /etc/sysctl.d/60-relay.conf <<EOF
net.ipv4.ip_forward = 1
net.ipv4.conf.all.rp_filter = 2
net.ipv4.conf.$IF.rp_filter = 2
# 투영 주소를 가로채는 정책 규칙(pref 50) 때문에 커널 ARP 판단이 "내 주소 아님"으로 나온다 → 대신 답하게
# (AWS VPC는 하이퍼바이저가 ARP를 답하므로 영향 없음. L2가 있는 곳에선 필요 — 11/22 로컬에서 확인)
net.ipv4.conf.$IF.proxy_arp = 1
EOF
sysctl -q -p /etc/sysctl.d/60-relay.conf

# 응답 경로: 투영 서브넷은 직접, 그 밖은 게이트웨이로
SUBNET=$(ip -4 route show dev "$IF" proto kernel scope link | awk 'NR==1{print $1}')
if [ "$GW" = "-" ]; then OUT_DEFAULT="default dev $IF"; else OUT_DEFAULT="default via $GW dev $IF"; fi
cat > /etc/wireguard/relay.conf <<EOF
[Interface]
PrivateKey = $(cat /etc/wireguard/relay.key)
Address = 10.200.0.1/30
Table = off
MTU = 1380
# local 테이블보다 먼저: 투영 주소로 들어온 것은 팜으로(local 규칙을 pref 0 → 1000으로 옮김)
PostUp = ip rule show pref 1000 | grep -q . || ip rule add pref 1000 lookup local
PostUp = ip rule del pref 0 lookup local 2>/dev/null || true
PostUp = ip rule show pref 50 | grep -q . || ip rule add pref 50 iif $IF to $X/32 lookup $T_IN
PostUp = ip route replace $X/32 dev %i table $T_IN
# 팜에서 돌아온 응답(출발지 = 투영 주소)은 투영 NIC로
PostUp = ip rule show pref 51 | grep -q . || ip rule add pref 51 iif %i from $X/32 lookup $T_OUT
PostUp = ip route replace $SUBNET dev $IF table $T_OUT
PostUp = ip route replace $OUT_DEFAULT table $T_OUT
PostUp = iptables -t mangle -C FORWARD -o %i -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || iptables -t mangle -A FORWARD -o %i -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
PreDown = ip rule del pref 50 2>/dev/null || true
PreDown = ip rule del pref 51 2>/dev/null || true

[Peer]
PublicKey = $FARM_PUB
Endpoint = $FARM
AllowedIPs = 10.200.0.2/32, $X/32
PersistentKeepalive = 25
EOF
chmod 600 /etc/wireguard/relay.conf
systemctl enable wg-quick@relay >/dev/null 2>&1
systemctl restart wg-quick@relay
echo "relay_public_key=$(wg pubkey < /etc/wireguard/relay.key)"
