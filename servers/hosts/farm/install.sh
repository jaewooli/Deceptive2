#!/usr/bin/env bash
# farm — 투영 팜(벤더 투영의 중앙 팜 쪽). 디코이는 systemd-nspawn OS 컨테이너, 센서와는 WireGuard로만 잇는다.
# root로, 여러 번 실행해도 결과가 같다.
#   sudo ./install.sh <센서 공개키> <컨테이너 이름> <투영 주소/접두> <투영 서브넷 게이트웨이>
#   예) 로컬: ./install.sh <키> stg-01 10.0.20.30/24 10.0.20.1    EC2: ./install.sh <키> stg-01 10.0.2.40/24 10.0.2.1
# 컨테이너 안에서 보이는 것: 자기 NIC에 투영 주소, 기본 게이트웨이 = 그 서브넷의 .1(팜 쪽 veth가 맡음, proxy ARP)
# 컨테이너 루트파일시스템은 <이름>/build.sh가 만든다(/var/lib/machines/<이름>)
# 키: 처음 실행 때 /etc/wireguard/relay.key를 만들고 공개키를 출력한다(저장소에 넣지 않음)
set -euo pipefail
SENSOR_PUB=${1:?센서 공개키}; NAME=${2:?컨테이너 이름}; ADDR=${3:?투영 주소/접두}; GW=${4:?게이트웨이}
X=${ADDR%/*}; VETH="ve-$NAME"; T_OUT=120
export DEBIAN_FRONTEND=noninteractive
dpkg -s wireguard-tools systemd-container debootstrap >/dev/null 2>&1 || apt-get install -y -q wireguard-tools systemd-container debootstrap

install -d -m 0700 /etc/wireguard
[ -f /etc/wireguard/relay.key ] || (umask 077; wg genkey > /etc/wireguard/relay.key)
cat > /etc/sysctl.d/60-relay.conf <<'EOF'
net.ipv4.ip_forward = 1
net.ipv4.conf.all.rp_filter = 2
EOF
sysctl -q -p /etc/sysctl.d/60-relay.conf

cat > /etc/wireguard/relay.conf <<EOF
[Interface]
PrivateKey = $(cat /etc/wireguard/relay.key)
Address = 10.200.0.2/30
ListenPort = 51820
Table = off
MTU = 1380
# 컨테이너 응답 경로는 터널 수명 주기에 묶는다 — 컨테이너 시작 스크립트에 두면 터널보다 먼저 돌아 경로표가 비고,
# 응답이 같은 LAN으로 바로 나가 터널을 우회한다(MSS 조정을 못 받아 큰 패킷이 터널 MTU에서 버려짐 — 11/23 SSH 키 교환 멈춤)
PostUp = ip route replace default dev %i table $T_OUT
PostUp = ip rule show pref 50 | grep -q . || ip rule add pref 50 iif $VETH lookup $T_OUT
PostUp = iptables -t mangle -C FORWARD -o %i -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || iptables -t mangle -A FORWARD -o %i -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu

[Peer]
PublicKey = $SENSOR_PUB
# 공격자 주소는 어디든 될 수 있다 → 컨테이너 응답은 모두 터널로(팜 자신의 기본 경로는 그대로, Table = off)
AllowedIPs = 0.0.0.0/0
EOF
chmod 600 /etc/wireguard/relay.conf
systemctl enable wg-quick@relay >/dev/null 2>&1
systemctl restart wg-quick@relay

# 컨테이너가 뜰 때 팜 쪽 veth: 게이트웨이 주소 + proxy ARP, 투영 주소 경로, 응답은 터널로
install -d /usr/local/lib/relay /etc/systemd/system/systemd-nspawn@"$NAME".service.d
# veth 주소·proxy ARP는 networkd 설정으로 고정(스크립트로 넣으면 기본 80-container-ve.network가 지운다 — 11/22 경쟁)
cat > /etc/systemd/network/10-$VETH.network <<EOF
[Match]
Name=$VETH

[Network]
Address=$GW/32
IPv4ProxyARP=yes
LinkLocalAddressing=no
IPv6AcceptRA=no
ConfigureWithoutCarrier=yes
EOF
# networkd는 기본값으로 자기가 만들지 않은 정책 규칙·경로를 지운다(wg-quick PostUp 규칙이 사라짐 — 11/22 재부팅 시험)
install -d /etc/systemd/networkd.conf.d
printf '[Network]\nManageForeignRoutingPolicyRules=no\nManageForeignRoutes=no\n' > /etc/systemd/networkd.conf.d/10-keep-foreign.conf
systemctl enable --now systemd-networkd >/dev/null 2>&1 || true
# 세션 안에서 바로 재시작하면 관리 접속(SSH)이 끊겨 멈춘다(11/22) → 분리해서
systemd-run --on-active=1 --unit=networkd-reload-$$ systemctl restart systemd-networkd >/dev/null 2>&1 || true
sleep 4
networkctl reload 2>/dev/null || true
cat > /usr/local/lib/relay/veth-up <<EOF
#!/bin/sh
# systemd-nspawn@$NAME 시작 뒤: 투영 주소 경로, 응답은 터널로. 실패해도 컨테이너를 내리지 않는다(11/22: veth보다 먼저 돌아 실패 → 컨테이너가 같이 내려감)
for i in \$(seq 50); do ip link show $VETH >/dev/null 2>&1 && break; sleep 0.2; done
sysctl -q -w net.ipv4.conf.$VETH.rp_filter=2 2>/dev/null
ip route replace $X/32 dev $VETH
# 컨테이너 경로가 빠지면 LAN으로 새지 않고 버린다(farm과 센서가 같은 망이면 루프 — 11/22)
ip route replace blackhole $X/32 metric 1000 2>/dev/null
# 응답 경로(table $T_OUT)·규칙은 wg-quick@relay PostUp이 건다
exit 0
EOF
chmod 755 /usr/local/lib/relay/veth-up
cat > /etc/systemd/system/systemd-nspawn@"$NAME".service.d/relay.conf <<EOF
[Unit]
After=wg-quick@relay.service systemd-networkd.service
Wants=wg-quick@relay.service
[Service]
ExecStartPost=/usr/local/lib/relay/veth-up
EOF
install -d /etc/systemd/nspawn
cat > /etc/systemd/nspawn/"$NAME".nspawn <<EOF
[Exec]
Boot=yes
PrivateUsers=no
[Network]
VirtualEthernet=yes
EOF
systemctl daemon-reload
echo "relay_public_key=$(wg pubkey < /etc/wireguard/relay.key)"
