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
MTU = 1380

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
Address=$GW/32
IPv4ProxyARP=yes
LinkLocalAddressing=no
IPv6AcceptRA=no
ConfigureWithoutCarrier=yes
EOF
systemctl enable --now systemd-networkd >/dev/null 2>&1 || true
networkctl reload 2>/dev/null || true
install -d /etc/systemd/nspawn /usr/local/lib/relay "/etc/systemd/system/systemd-nspawn@$NAME.service.d"
printf '[Exec]\nBoot=yes\nPrivateUsers=no\n[Network]\nVirtualEthernet=yes\n' > "/etc/systemd/nspawn/$NAME.nspawn"
cat > "/usr/local/lib/relay/trap-$NAME-up" <<EOF
#!/bin/sh
for i in \$(seq 50); do ip link show ve-$NAME >/dev/null 2>&1 && break; sleep 0.2; done
sysctl -q -w net.ipv4.ip_forward=1 net.ipv4.conf.all.rp_filter=2 net.ipv4.conf.ve-$NAME.rp_filter=2 net.ipv4.conf.$WG.rp_filter=2
# 터널에서 온 것(목적지 = EDH 주소) → 컨테이너. farm 자신의 EDH 가는 길(main)은 그대로
ip rule show pref $((60 + N)) | grep -q . || ip rule add pref $((60 + N)) iif $WG lookup $T_IN
ip route replace $EIP/32 dev ve-$NAME table $T_IN
# 컨테이너 응답 → 그 EDH 터널
ip rule show pref $((61 + N + 100)) | grep -q . || ip rule add pref $((61 + N + 100)) iif ve-$NAME lookup $T_OUT
ip route replace default dev $WG table $T_OUT
nft delete table ip trap_$N 2>/dev/null || true
EOF
chmod 755 "/usr/local/lib/relay/trap-$NAME-up"
printf '[Service]\nExecStartPost=/usr/local/lib/relay/trap-%s-up\n' "$NAME" > "/etc/systemd/system/systemd-nspawn@$NAME.service.d/relay.conf"
systemctl daemon-reload
systemctl enable "systemd-nspawn@$NAME" >/dev/null 2>&1
systemctl restart "systemd-nspawn@$NAME"
for i in $(seq 60); do systemd-run -M "$NAME" -q --wait -P systemctl is-system-running --wait >/dev/null 2>&1 && break; sleep 1; done
echo "farm_tunnel_public_key=$(wg pubkey < /etc/wireguard/$WG.key) port=$((51820 + N))"
echo "trap $NAME($EDH) $SVC: 터널 $WG → $EIP:$INT — $(systemd-run -M "$NAME" -q --wait -P sh -c "hostname; ss -Hltn | awk '{print \$4}' | tr '\n' ' '")"
