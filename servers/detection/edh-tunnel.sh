#!/usr/bin/env bash
# EDH(실제 운영 서버)가 자기 안 쓰는 포트로 온 연결을 farm 트랩으로 넘기는 터널. root로, 여러 번 실행해도 결과가 같다.
#   sudo ./edh-tunnel.sh <farm 엔드포인트 host:port> <farm 터널 공개키>
# 인터페이스만 만든다(주소·경로표 없음, Table = off). 어느 포트를 넘길지는 moa-notify의 ports 감시가 정책 규칙으로 관리
# 키: 처음 실행 때 /etc/wireguard/wg0.key를 만들고 공개키를 출력한다(저장소에 넣지 않음)
set -euo pipefail
EP=${1:?farm 엔드포인트}; FPUB=${2:?farm 공개키}
export DEBIAN_FRONTEND=noninteractive
command -v wg >/dev/null || apt-get install -y -q wireguard-tools >/dev/null
install -d -m 0700 /etc/wireguard
[ -f /etc/wireguard/wg0.key ] || (umask 077; wg genkey > /etc/wireguard/wg0.key)
cat > /etc/wireguard/wg0.conf <<CONF
[Interface]
PrivateKey = $(cat /etc/wireguard/wg0.key)
Table = off
# MTU = 구간(LAN·VPC) MTU 그대로(로컬 1500, AWS 9001). 바깥 UDP는 IP 단편화에 맡긴다(WireGuard는 바깥 패킷에 DF를 안 건다).
# 11/23 실측: 1380 + MSS 조정이면 공격자 SYN-ACK에 MSS 1340(이웃은 1460)·DF 1472 ping 소실·tracepath 무응답 → 디코이가 터널 뒤임이 드러남
MTU = $(cat /sys/class/net/"$(ip -o route get 1.1.1.1 | sed -n 's/.* dev \([^ ]*\).*/\1/p')"/mtu)

[Peer]
PublicKey = $FPUB
Endpoint = $EP
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
CONF
chmod 600 /etc/wireguard/wg0.conf
systemctl enable wg-quick@wg0 >/dev/null 2>&1; systemctl restart wg-quick@wg0
echo "edh_public_key=$(wg pubkey < /etc/wireguard/wg0.key)"
