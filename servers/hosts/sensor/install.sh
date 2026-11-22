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

# 투영 NIC: 투영 주소를 센서 자신의 주소로 두지 않는다 — 자기 주소면 local 경로표보다 먼저 가로채려고 local 규칙을 옮겨야 하는데,
# networkd가 재시작하며 그 규칙을 지우면 센서 전체가 먹통이 된다(11/22 실측). 대신 투영 주소 경로를 터널로(main /32):
#   AWS: VPC가 투영 ENI의 주소로 온 패킷을 ENI로 넘겨준다(OS 설정 불필요). 로컬 L2: proxy ARP가 대신 답한다(경로가 다른 NIC라서)
cat > /etc/netplan/60-relay.yaml <<EOF
network:
  version: 2
  ethernets:
    $IF:
      dhcp4: false
      dhcp6: false
      accept-ra: false
      link-local: []
      # 로컬 L2에서 proxy ARP가 답하려면 그 NIC에 IPv4가 하나 있어야 한다(투영과 무관한 링크 로컬). AWS는 하이퍼바이저가 ARP를 답해 불필요(무해)
      addresses: [169.254.31.1/32]
EOF
chmod 600 /etc/netplan/60-relay.yaml
netplan apply

cat > /etc/sysctl.d/60-relay.conf <<EOF
net.ipv4.ip_forward = 1
net.ipv4.conf.all.rp_filter = 2
net.ipv4.conf.$IF.rp_filter = 2
net.ipv4.conf.$IF.proxy_arp = 1
EOF
sysctl -q -p /etc/sysctl.d/60-relay.conf
# networkd가 자기가 만들지 않은 규칙·경로를 지우지 않게(아래 응답 규칙)
install -d /etc/systemd/networkd.conf.d
printf '[Network]\nManageForeignRoutingPolicyRules=no\nManageForeignRoutes=no\n' > /etc/systemd/networkd.conf.d/10-keep-foreign.conf
# 세션 안에서 바로 재시작하면 관리 접속(SSH)이 끊겨 멈춘다(11/22) → 분리해서
systemd-run --on-active=1 --unit=networkd-reload-$$ systemctl restart systemd-networkd >/dev/null 2>&1 || true
sleep 4

SUBNET=$(python3 -c "import ipaddress,sys; print(ipaddress.ip_interface(sys.argv[1]).network)" "$ADDR")
if [ "$GW" = "-" ]; then OUT_DEFAULT="default dev $IF"; else OUT_DEFAULT="default via $GW dev $IF onlink"; fi
cat > /etc/wireguard/relay.conf <<EOF
[Interface]
PrivateKey = $(cat /etc/wireguard/relay.key)
Address = 10.200.0.1/30
Table = off
# MTU = 구간(LAN·VPC) MTU 그대로(로컬 1500, AWS 9001). 바깥 UDP는 IP 단편화에 맡긴다(WireGuard는 바깥 패킷에 DF를 안 건다).
# 11/23 실측: 1380 + MSS 조정이면 공격자 SYN-ACK에 MSS 1340(이웃은 1460)·DF 1472 ping 소실·tracepath 무응답 → 디코이가 터널 뒤임이 드러남
MTU = $(cat /sys/class/net/$IF/mtu)
# 투영 주소 → 터널(main /32, 규칙 아님 — 지워져도 센서는 멀쩡, 터널이 다시 뜨면 다시 걸림)
PostUp = ip route replace $X/32 dev %i
# 팜에서 돌아온 응답(출발지 = 투영 주소)은 투영 NIC로(이 규칙이 지워지면 투영만 멈춤)
PostUp = ip rule show pref 51 | grep -q . || ip rule add pref 51 iif %i from $X/32 lookup $T_OUT
PostUp = ip route replace $SUBNET dev $IF table $T_OUT
PostUp = ip route replace $OUT_DEFAULT table $T_OUT
# 포워딩 홉마다 TTL이 1 준다 → 투영 디코이가 같은 서브넷인데 TTL 62로 보임(11/23 실측). 들어올 때 1을 되돌린다(양방향: 응답 TTL 64, traceroute에 홉 없음)
PostUp = iptables -w -t mangle -C PREROUTING -i %i -j TTL --ttl-inc 1 2>/dev/null || iptables -w -t mangle -A PREROUTING -i %i -j TTL --ttl-inc 1
PostUp = iptables -w -t mangle -C PREROUTING -i $IF -d $X/32 -j TTL --ttl-inc 1 2>/dev/null || iptables -w -t mangle -A PREROUTING -i $IF -d $X/32 -j TTL --ttl-inc 1
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
