#!/usr/bin/env bash
# farm — 투영 팜(벤더 투영의 중앙 팜 쪽). 디코이는 KVM VM(guest/guest.sh, 11/23 결정 B), 센서와는 WireGuard로만 잇는다.
# root로, 여러 번 실행해도 결과가 같다.
#   sudo PERSIST=true|false ./install.sh <센서 공개키>
#   PERSIST(환경 프로필 farm.persist): true = 재부팅 뒤 자동으로(AWS), false = 런타임만 — sysctl 파일·유닛 enable 없음(WSL2 팜, docs/local-farm-recovery.md)
# 이 스크립트는 센서와의 터널(relay)과 응답 경로표(120)만. 디코이(KVM VM)·디코이별 응답 규칙·탭 주소는 guest/guest.sh
# 디코이 안에서 보이는 것: 자기 NIC에 투영 주소, 기본 게이트웨이 = 그 서브넷의 .1(팜 쪽 탭이 맡음, proxy ARP)
# 키: 처음 실행 때 /etc/wireguard/relay.key를 만들고 공개키를 출력한다(저장소에 넣지 않음)
set -euo pipefail
SENSOR_PUB=${1:?센서 공개키}; T_OUT=120; PERSIST=${PERSIST:?PERSIST=true|false}
NOTIFY_URL=${NOTIFY_URL:?NOTIFY_URL(환경 프로필 notify.farm_webhook_url)}; NOTIFY_FORMAT=${NOTIFY_FORMAT:-json}
# 디코이 apt 요청을 시점 고정 미러로(재블렌딩, 환경 프로필 guest.mirror_intercept): "주소:포트"(로컬 — 디코이의 apt 프록시) / "*:80"(AWS — 투명)
MIRROR_INTERCEPT=${MIRROR_INTERCEPT:?MIRROR_INTERCEPT}
case $MIRROR_INTERCEPT in "*:"*) MATCH="tcp dport ${MIRROR_INTERCEPT#*:}" ;; *) MATCH="ip daddr ${MIRROR_INTERCEPT%:*} tcp dport ${MIRROR_INTERCEPT#*:}" ;; esac
HERE=$(cd "$(dirname "$0")" && pwd)
export DEBIAN_FRONTEND=noninteractive
dpkg -s wireguard-tools systemd-container >/dev/null 2>&1 || apt-get install -y -q wireguard-tools systemd-container

install -d -m 0700 /etc/wireguard
[ -f /etc/wireguard/relay.key ] || (umask 077; wg genkey > /etc/wireguard/relay.key)
# 다른 NIC에 붙은 자기 주소로는 ARP에 답하지 않는다 — 탭·veth 쪽 주소로 LAN의 ARP를 가로채지 않게(11/23 구간 분리: 라우터 .1 충돌)
SYSCTL="net.ipv4.ip_forward=1 net.ipv4.conf.all.rp_filter=2 net.ipv4.conf.all.arp_ignore=1"
if [ "$PERSIST" = true ]; then
  printf '%s\n' $SYSCTL | sed 's/=/ = /' > /etc/sysctl.d/60-relay.conf; sysctl -q -p /etc/sysctl.d/60-relay.conf
else
  rm -f /etc/sysctl.d/60-relay.conf; sysctl -q -w $SYSCTL
fi

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
# Docker가 있는 팜(WSL2)은 FORWARD 기본 정책이 DROP일 수 있다 → 팜 인터페이스끼리만 허용(DOCKER-USER는 Docker 규칙보다 먼저 봄)
PostUp = iptables -w -n -L DOCKER-USER >/dev/null 2>&1 && for x in "-i %i" "-o %i" "-i ve-+" "-o ve-+" "-i edh+" "-o edh+"; do iptables -w -C DOCKER-USER \$x -j ACCEPT 2>/dev/null || iptables -w -I DOCKER-USER \$x -j ACCEPT; done; true
# 팜 쪽 탐지(Acalvio — 디코이 밖에서, 11/23 특허 원문 확인): 터널에서 디코이로 넘어가는 새 연결을 커널 로그로(초당 20개 한도 — 스캔에 넘치지 않게).
# relay-notify가 읽어 경보. 터널과 같이 생기고 같이 사라진다(투영 끔 = 흔적 없음)
PostUp = nft -f - <<< "table ip proj_watch { chain watch_in { type filter hook forward priority -1; policy accept; iifname \"%i\" ct state new limit rate 20/second log prefix \"PROJ-IN \"; }; }"
PreDown = nft delete table ip proj_watch 2>/dev/null || true
# 연결 수립 지연(/etc/relay/tarpit.ms가 있을 때만 — 관리 쪽 스위치): 수집 쪽이 출발지에 도착할 때까지 짧은 연결을 붙잡는다
PostUp = [ -f /etc/relay/tarpit.ms ] && /usr/local/lib/relay/tarpit on %i "\$(cat /etc/relay/tarpit.ms)" || true
PreDown = /usr/local/lib/relay/tarpit off %i || true
# 디코이의 apt 요청 → 시점 고정 미러(relay-mirror, 탭 주소 169.254.31.2:3144). 이웃과 같은 스냅숏만 보임 — 디코이는 자기 unattended-upgrades로 따라감
PostUp = nft -f - <<< "table ip proj_mirror { chain pre { type nat hook prerouting priority dstnat; policy accept; iifname \"ve-*\" $MATCH dnat to 169.254.31.2:3144; }; }"
PreDown = nft delete table ip proj_mirror 2>/dev/null || true

[Peer]
PublicKey = $SENSOR_PUB
# 공격자 주소는 어디든 될 수 있다 → 컨테이너 응답은 모두 터널로(팜 자신의 기본 경로는 그대로, Table = off)
AllowedIPs = 0.0.0.0/0
EOF
chmod 600 /etc/wireguard/relay.conf
# 팜 경보 데몬 — 같은 moa-notify 코드, 투영 감시만. relay와 수명을 같이(Wants·PartOf)
install -d -m 0755 /usr/local/lib/relay; install -d -m 0700 /etc/relay /var/lib/relay-notify
install -m 0644 "$HERE/../../detection/moa-notify/moa_notify.py" /usr/local/lib/relay/notify.py
install -m 0644 "$HERE/guest/mirror.py" /usr/local/lib/relay/mirror.py
install -m 0755 "$HERE/tarpit.sh" /usr/local/lib/relay/tarpit
cat > /etc/relay/notify.json <<EOF
{"hostname": "farm", "webhook_url": "$NOTIFY_URL", "format": "$NOTIFY_FORMAT", "max_per_minute": 30, "poll_seconds": 0.5,
 "state_file": "/var/lib/relay-notify/state.json",
 "watch": {"projection": {"enabled": true, "path": "/var/log/kern.log", "prefix": "PROJ-IN", "guest_env_dir": "/etc/guest"}}}
EOF
chmod 600 /etc/relay/notify.json
cat > /etc/systemd/system/relay-notify.service <<'EOF'
[Unit]
Description=relay notify
After=wg-quick@relay.service
PartOf=wg-quick@relay.service
[Service]
ExecStart=/usr/bin/python3 /usr/local/lib/relay/notify.py --config /etc/relay/notify.json
Restart=on-failure
EOF
cat > /etc/systemd/system/relay-mirror.service <<'EOF'
[Unit]
Description=relay mirror
After=wg-quick@relay.service
PartOf=wg-quick@relay.service
[Service]
ExecStart=/usr/bin/python3 /usr/local/lib/relay/mirror.py --bind 169.254.31.2 --port 3144 --env-dir /etc/guest
Restart=on-failure
EOF
install -d /etc/systemd/system/wg-quick@relay.service.d
printf '[Unit]\nWants=relay-notify.service relay-mirror.service\n' > /etc/systemd/system/wg-quick@relay.service.d/notify.conf
systemctl daemon-reload
if [ "$PERSIST" = true ]; then systemctl enable wg-quick@relay >/dev/null 2>&1; else systemctl disable wg-quick@relay >/dev/null 2>&1 || true; fi
systemctl restart wg-quick@relay
systemctl restart relay-notify relay-mirror

# networkd는 기본값으로 자기가 만들지 않은 정책 규칙·경로를 지운다(wg-quick PostUp 규칙이 사라짐 — 11/22 재부팅 시험).
# networkd를 쓰는 팜(AWS)에서만 — WSL2는 networkd가 없다(켜면 WSL의 eth0·규칙과 부딪힘)
if systemctl is-enabled -q systemd-networkd 2>/dev/null; then
  install -d /etc/systemd/networkd.conf.d
  printf '[Network]\nManageForeignRoutingPolicyRules=no\nManageForeignRoutes=no\n' > /etc/systemd/networkd.conf.d/10-keep-foreign.conf
fi
echo "relay_public_key=$(wg pubkey < /etc/wireguard/relay.key)"
