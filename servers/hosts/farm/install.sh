#!/usr/bin/env bash
# farm — 투영 팜(벤더 투영의 중앙 팜 쪽). 디코이는 KVM VM(guest/guest.sh, 11/23 결정 B), 센서와는 WireGuard로만 잇는다.
# root로, 여러 번 실행해도 결과가 같다.
#   sudo ./install.sh <센서 공개키>
# 이 스크립트는 센서와의 터널(relay)과 응답 경로표(120)만. 디코이(KVM VM)·디코이별 응답 규칙·탭 주소는 guest/guest.sh
# 디코이 안에서 보이는 것: 자기 NIC에 투영 주소, 기본 게이트웨이 = 그 서브넷의 .1(팜 쪽 탭이 맡음, proxy ARP)
# 키: 처음 실행 때 /etc/wireguard/relay.key를 만들고 공개키를 출력한다(저장소에 넣지 않음)
set -euo pipefail
SENSOR_PUB=${1:?센서 공개키}; T_OUT=120
export DEBIAN_FRONTEND=noninteractive
dpkg -s wireguard-tools systemd-container >/dev/null 2>&1 || apt-get install -y -q wireguard-tools systemd-container

install -d -m 0700 /etc/wireguard
[ -f /etc/wireguard/relay.key ] || (umask 077; wg genkey > /etc/wireguard/relay.key)
cat > /etc/sysctl.d/60-relay.conf <<'EOF'
net.ipv4.ip_forward = 1
net.ipv4.conf.all.rp_filter = 2
# 다른 NIC에 붙은 자기 주소로는 ARP에 답하지 않는다 — 탭·veth 쪽 주소로 LAN의 ARP를 가로채지 않게(11/23 구간 분리: 라우터 .1 충돌)
net.ipv4.conf.all.arp_ignore = 1
EOF
sysctl -q -p /etc/sysctl.d/60-relay.conf

cat > /etc/wireguard/relay.conf <<EOF
[Interface]
PrivateKey = $(cat /etc/wireguard/relay.key)
Address = 10.200.0.2/30
ListenPort = 51820
Table = off
# MTU = 구간(LAN·VPC) MTU 그대로(로컬 1500, AWS 9001). 바깥 UDP는 IP 단편화에 맡긴다(WireGuard는 바깥 패킷에 DF를 안 건다).
# 11/23 실측: 1380 + MSS 조정이면 공격자 SYN-ACK에 MSS 1340(이웃은 1460)·DF 1472 ping 소실·tracepath 무응답 → 디코이가 터널 뒤임이 드러남
MTU = ${SEGMENT_MTU:-$(cat /sys/class/net/"$(ip -o route get 1.1.1.1 | sed -n 's/.* dev \([^ ]*\).*/\1/p')"/mtu)}
# 디코이 응답 경로는 터널 수명 주기에 묶는다 — 디코이 시작 스크립트에 두면 터널보다 먼저 돌아 경로표가 비고,
# 응답이 같은 LAN으로 바로 나가 터널을 우회한다(11/23 SSH 키 교환 멈춤). 디코이별 규칙(iif ve-<이름> → $T_OUT)은 guest-up이 걸고,
# 터널이 없을 때를 위해 $T_OUT에 unreachable 예비 경로를 둔다(새지 않고 버림 — fail-closed)
PostUp = ip route replace default dev %i table $T_OUT

# 포워딩 홉마다 TTL이 1 준다 → 투영 디코이가 같은 서브넷인데 TTL 62로 보임(11/23 실측). 들어올 때 1을 되돌린다(양방향: 응답 TTL 64, traceroute에 홉 없음)
PostUp = iptables -w -t mangle -C PREROUTING -i %i -j TTL --ttl-inc 1 2>/dev/null || iptables -w -t mangle -A PREROUTING -i %i -j TTL --ttl-inc 1
PostUp = iptables -w -t mangle -C PREROUTING -i ve-+ -j TTL --ttl-inc 1 2>/dev/null || iptables -w -t mangle -A PREROUTING -i ve-+ -j TTL --ttl-inc 1

[Peer]
PublicKey = $SENSOR_PUB
# 공격자 주소는 어디든 될 수 있다 → 컨테이너 응답은 모두 터널로(팜 자신의 기본 경로는 그대로, Table = off)
AllowedIPs = 0.0.0.0/0
EOF
chmod 600 /etc/wireguard/relay.conf
systemctl enable wg-quick@relay >/dev/null 2>&1
systemctl restart wg-quick@relay

# networkd는 기본값으로 자기가 만들지 않은 정책 규칙·경로를 지운다(wg-quick PostUp 규칙이 사라짐 — 11/22 재부팅 시험)
install -d /etc/systemd/networkd.conf.d
printf '[Network]\nManageForeignRoutingPolicyRules=no\nManageForeignRoutes=no\n' > /etc/systemd/networkd.conf.d/10-keep-foreign.conf
# 11/23까지의 컨테이너 디코이 흔적 정리(디코이는 이제 guest/guest.sh의 KVM VM)
for n in $(ls /etc/systemd/nspawn 2>/dev/null | sed -n 's/\.nspawn$//p' | grep -v '^trap-'); do
  systemctl disable --now "systemd-nspawn@$n" >/dev/null 2>&1 || true
  rm -rf "/etc/systemd/nspawn/$n.nspawn" "/etc/systemd/system/systemd-nspawn@$n.service.d"
  findmnt -rno SOURCE "/var/lib/machines/$n" >/dev/null || rm -rf "/var/lib/machines/$n"   # 옛 루트파일시스템(같은 자리가 VM 디스크 마운트 지점)
done
rm -f /usr/local/lib/relay/veth-up
systemctl daemon-reload
echo "relay_public_key=$(wg pubkey < /etc/wireguard/relay.key)"
