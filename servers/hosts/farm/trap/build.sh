#!/usr/bin/env bash
# 트랩 컨테이너 — Illusive 트랩 서버(US10404747): 운영 서버(EDH)의 안 쓰는 포트로 온 연결을 받아 진짜 서비스로 응답.
# EDH마다 하나. 컨테이너는 **EDH 주소를 자기 NIC에** 갖고(hostname도 EDH), EDH와는 WireGuard 터널로만 잇는다(주소 변환 없음 —
# 11/22 masquerade로 했더니 Redis CLIENT LIST에 addr=EDH 자신·laddr=트랩 내부 주소가 보여 중계가 드러남)
# farm에서 root로, 여러 번 실행해도 결과가 같다.
#   sudo ./build.sh <컨테이너> <EDH 이름> <번호 1~250> <서비스: redis|nginx-auth> <서비스 포트> <EDH 주소/접두> <EDH 서브넷 게이트웨이> <EDH 터널 공개키>
# farm 쪽: 터널 edh<번호>(포트 51820+번호, 상대 = 그 EDH, AllowedIPs 0.0.0.0/0 → EDH마다 인터페이스 하나)
#   터널로 들어온 것(목적지 = EDH 주소) → 컨테이너 veth, 컨테이너 응답 → 그 터널. farm 자신의 경로표는 건드리지 않는다(정책 라우팅)
# 루트파일시스템: 공식 클라우드 이미지 루트 tarball(SHA256 검증) — debootstrap보다 EC2 서버와 패키지가 같다(11/22 stg-01 측정 D2·D3)
set -euo pipefail
NAME=${1:?이름}; EDH=${2:?EDH 이름}; N=${3:?번호}; SVC=${4:?서비스}; INT=${5:?서비스 포트}; EADDR=${6:?EDH 주소/접두}; GW=${7:?게이트웨이}; EPUB=${8:?EDH 공개키}
EIP=${EADDR%/*}; WG=edh$N; T_IN=$((140 + N)); T_OUT=$((190 + N))
ROOT=/var/lib/machines/$NAME
IMG=https://cloud-images.ubuntu.com/noble/current
TAR=/var/cache/trap/noble-server-cloudimg-amd64-root.tar.xz
NS=(systemd-nspawn -q --settings=false --register=no --resolv-conf=bind-uplink -D "$ROOT" --pipe --)
export DEBIAN_FRONTEND=noninteractive
dpkg -s systemd-container wireguard-tools >/dev/null 2>&1 || apt-get install -y -q systemd-container wireguard-tools >/dev/null

install -d /var/cache/trap
if [ ! -f "$TAR" ]; then
  (cd /var/cache/trap && curl -fsSLO "$IMG/SHA256SUMS" && curl -fsSLO "$IMG/$(basename "$TAR")" &&
   grep " \*\?$(basename "$TAR")$" SHA256SUMS | sha256sum -c - >/dev/null)
fi
if [ ! -x "$ROOT/usr/bin/systemctl" ]; then
  systemctl stop "systemd-nspawn@$NAME" 2>/dev/null || true
  rm -rf "$ROOT"; install -d "$ROOT"
  tar -C "$ROOT" -xJf "$TAR"
fi

# 클라우드 이미지 그대로 + 컨테이너에서 못 도는 첫 부팅 도구만 끔(cloud-init은 메타데이터를 찾다 멈춘다)
touch "$ROOT/etc/cloud/cloud-init.disabled"
echo "$EDH" > "$ROOT/etc/hostname"
sed -i "s/^127\.0\.1\.1 .*/127.0.1.1 $EDH/" "$ROOT/etc/hosts" 2>/dev/null; grep -q "127.0.1.1" "$ROOT/etc/hosts" || echo "127.0.1.1 $EDH" >> "$ROOT/etc/hosts"
ln -sf /usr/share/zoneinfo/Asia/Seoul "$ROOT/etc/localtime"; echo Asia/Seoul > "$ROOT/etc/timezone"
rm -f "$ROOT"/etc/netplan/*.yaml
install -d "$ROOT/etc/systemd/network"
cat > "$ROOT/etc/systemd/network/10-host0.network" <<EOF
[Match]
Name=host0

[Network]
Address=$EADDR
Gateway=$GW
EOF

# 같은 패치 수준 + 서비스(떠 있으면 멈춘 뒤 — 같은 디렉터리로 nspawn을 두 번 못 띄움)
systemctl stop "systemd-nspawn@$NAME" 2>/dev/null || true
"${NS[@]}" bash -c 'apt-get update -q >/dev/null && apt-get -y -q full-upgrade >/dev/null'
case "$SVC" in
  redis)
    # 흔한 잘못된 설정: 내부망이라 bind 전체·보호 모드 끔·비밀번호 없음(공격자가 실제로 노리는 모양)
    "${NS[@]}" bash -c 'apt-get install -y -q redis-server >/dev/null'
    sed -i -e 's/^bind .*/bind 0.0.0.0/' -e 's/^protected-mode yes/protected-mode no/' "$ROOT/etc/redis/redis.conf"
    "${NS[@]}" systemctl enable redis-server >/dev/null 2>&1 ;;
  nginx-auth)
    # 내부 관리용 포트: 진짜 nginx + Basic 인증(인증 없이는 401)
    "${NS[@]}" bash -c 'apt-get install -y -q nginx apache2-utils >/dev/null'
    "${NS[@]}" bash -c "htpasswd -bc /etc/nginx/.htpasswd admin '$(head -c 18 /dev/urandom | base64)' >/dev/null"
    cat > "$ROOT/etc/nginx/sites-available/default" <<EOF
server {
    listen $INT default_server;
    server_name _;
    auth_basic "Restricted";
    auth_basic_user_file /etc/nginx/.htpasswd;
    root /var/www/html;
}
EOF
    "${NS[@]}" systemctl enable nginx >/dev/null 2>&1 ;;
  *) echo "서비스? $SVC" >&2; exit 2 ;;
esac
"${NS[@]}" systemctl enable systemd-networkd >/dev/null 2>&1 || true

# farm 쪽: EDH 터널 + 컨테이너 veth(게이트웨이 .1 + proxy ARP, networkd로 고정 — 11/22 경쟁)
install -d -m 0700 /etc/wireguard
[ -f "/etc/wireguard/$WG.key" ] || (umask 077; wg genkey > "/etc/wireguard/$WG.key")
cat > "/etc/wireguard/$WG.conf" <<EOF
[Interface]
PrivateKey = $(cat "/etc/wireguard/$WG.key")
ListenPort = $((51820 + N))
Table = off
# MTU = 구간(LAN·VPC) MTU 그대로(로컬 1500, AWS 9001). 바깥 UDP는 IP 단편화에 맡긴다(WireGuard는 바깥 패킷에 DF를 안 건다).
# 11/23 실측: 1380 + MSS 조정이면 공격자 SYN-ACK에 MSS 1340(이웃은 1460)·DF 1472 ping 소실·tracepath 무응답 → 디코이가 터널 뒤임이 드러남
MTU = ${SEGMENT_MTU:-$(cat /sys/class/net/"$(ip -o route get 1.1.1.1 | sed -n 's/.* dev \([^ ]*\).*/\1/p')"/mtu)}

# 터널 쪽 규칙·응답 경로는 터널 수명 주기에 묶는다(시작 스크립트로 하면 터널보다 먼저 돌아 빠짐 — 11/22 재부팅 시험)
# EDH는 터널 안 주소(169.254.200.1)로 DNAT해 보낸다 → 여기서 다시 EDH 주소로 DNAT(컨테이너가 EDH 주소를 가짐). conntrack이 응답을 되돌림
PostUp = nft -f - <<< "table ip edh_$N { chain pre { type nat hook prerouting priority dstnat; policy accept; iifname \"%i\" ip daddr 169.254.200.1 dnat to $EIP; }; }"
PostUp = ip rule show pref $((60 + N)) | grep -q . || ip rule add pref $((60 + N)) iif %i lookup $T_IN
PostUp = ip route replace default dev %i table $T_OUT
# 포워딩 홉마다 TTL이 1 준다 → EDH의 22번은 TTL 64, 넘긴 포트는 62(11/23 실측). 들어올 때 1을 되돌린다(EDH 쪽은 moa-notify)
PostUp = iptables -w -t mangle -C PREROUTING -i %i -j TTL --ttl-inc 1 2>/dev/null || iptables -w -t mangle -A PREROUTING -i %i -j TTL --ttl-inc 1
PostUp = iptables -w -t mangle -C PREROUTING -i ve-+ -j TTL --ttl-inc 1 2>/dev/null || iptables -w -t mangle -A PREROUTING -i ve-+ -j TTL --ttl-inc 1
PreDown = ip rule del pref $((60 + N)) 2>/dev/null || true
PreDown = nft delete table ip edh_$N 2>/dev/null || true

[Peer]
PublicKey = $EPUB
AllowedIPs = 0.0.0.0/0
EOF
chmod 600 "/etc/wireguard/$WG.conf"
systemctl enable "wg-quick@$WG" >/dev/null 2>&1; systemctl restart "wg-quick@$WG"
cat > "/etc/systemd/network/10-ve-$NAME.network" <<EOF
[Match]
Name=ve-$NAME

[Network]
# 게이트웨이(.1)를 팜 자신의 주소로 두지 않는다 — 두면 팜이 LAN에서 진짜 라우터(.1)의 ARP를 가로챈다(Linux는 어느 NIC로 온 ARP든
# 자기 주소면 답함, 11/23 구간 분리 때 발견). 탭엔 링크 로컬만, 게이트웨이 ARP는 proxy ARP가 답한다(팜이 그 주소로 가는 경로를 LAN 쪽에 가짐)
Address=169.254.31.2/32
IPv4ProxyARP=yes
LinkLocalAddressing=no
IPv6AcceptRA=no
ConfigureWithoutCarrier=yes

# veth 쪽 경로·규칙은 networkd가 링크가 생길 때 건다(선언형 — 순서 경쟁 없음)
[Route]
Destination=$EIP/32
Table=$T_IN

[RoutingPolicyRule]
IncomingInterface=ve-$NAME
Table=$T_OUT
Priority=$((161 + N))
EOF
# networkd는 기본값으로 자기가 만들지 않은 정책 규칙·경로를 지운다(wg-quick PostUp 규칙이 사라짐 — 11/22 재부팅 시험)
install -d /etc/systemd/networkd.conf.d
printf '[Network]\nManageForeignRoutingPolicyRules=no\nManageForeignRoutes=no\n' > /etc/systemd/networkd.conf.d/10-keep-foreign.conf
systemctl enable --now systemd-networkd >/dev/null 2>&1 || true
# 세션 안에서 바로 재시작하면 관리 접속(SSH)이 끊겨 멈춘다(11/22) → 분리해서
systemd-run --on-active=1 --unit=networkd-reload-$$ systemctl restart systemd-networkd >/dev/null 2>&1 || true
sleep 4
networkctl reload 2>/dev/null || true
install -d /etc/systemd/nspawn /usr/local/lib/relay "/etc/systemd/system/systemd-nspawn@$NAME.service.d"
printf '[Exec]\nBoot=yes\nPrivateUsers=no\n[Network]\nVirtualEthernet=yes\n' > "/etc/systemd/nspawn/$NAME.nspawn"
cat > "/usr/local/lib/relay/trap-$NAME-up" <<EOF
#!/bin/sh
# 규칙·경로는 wg-quick(PostUp)·networkd가 건다. 여기선 커널 값만(없는 인터페이스는 건너뜀)
sysctl -q -w net.ipv4.ip_forward=1 net.ipv4.conf.all.rp_filter=2
for i in ve-$NAME $WG; do [ -e /proc/sys/net/ipv4/conf/\$i ] && sysctl -q -w net.ipv4.conf.\$i.rp_filter=2; done
nft delete table ip trap_$N 2>/dev/null || true
exit 0
EOF
chmod 755 "/usr/local/lib/relay/trap-$NAME-up"
printf '[Unit]\nAfter=wg-quick@%s.service systemd-networkd.service\nWants=wg-quick@%s.service\n[Service]\nExecStartPost=/usr/local/lib/relay/trap-%s-up\n' "$WG" "$WG" "$NAME" > "/etc/systemd/system/systemd-nspawn@$NAME.service.d/relay.conf"
systemctl daemon-reload
systemctl enable "systemd-nspawn@$NAME" >/dev/null 2>&1
systemctl restart "systemd-nspawn@$NAME"
for i in $(seq 60); do systemd-run -M "$NAME" -q --wait -P systemctl is-system-running --wait >/dev/null 2>&1 && break; sleep 1; done
echo "farm_tunnel_public_key=$(wg pubkey < /etc/wireguard/$WG.key) port=$((51820 + N))"
echo "trap $NAME($EDH) $SVC: 터널 $WG → $EIP:$INT — $(systemd-run -M "$NAME" -q --wait -P sh -c "hostname; ss -Hltn | awk '{print \$4}' | tr '\n' ' '")"
