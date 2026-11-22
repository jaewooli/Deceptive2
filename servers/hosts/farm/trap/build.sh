#!/usr/bin/env bash
# 트랩 컨테이너 — Illusive 트랩 서버(US10404747): 운영 서버(EDH)의 안 쓰는 포트로 온 연결을 받아 진짜 서비스로 응답.
# EDH마다 하나(hostname = 그 EDH, 같은 Ubuntu 클라우드 이미지·같은 패치 수준 — 공격자에겐 EDH가 그 서비스를 돌리는 것으로 보임)
# farm에서 root로, 여러 번 실행해도 결과가 같다.
#   sudo ./build.sh <컨테이너 이름> <EDH 호스트 이름> <번호 1~250> <서비스: redis|nginx-auth> <바깥 포트> <서비스 포트> <farm LAN 주소>
# 망: 컨테이너 host0 = 10.201.<번호>.2/30, 게이트웨이 .1(farm veth). farm은 <farm LAN 주소>:<바깥 포트> → 컨테이너:<서비스 포트>
# 루트파일시스템: 공식 클라우드 이미지 루트 tarball(SHA256 검증) — debootstrap보다 EC2 서버와 패키지가 같다(11/22 stg-01 측정 D2·D3)
set -euo pipefail
NAME=${1:?이름}; EDH=${2:?EDH 이름}; N=${3:?번호}; SVC=${4:?서비스}; EXT=${5:?바깥 포트}; INT=${6:?서비스 포트}; FARM=${7:?farm 주소}
ROOT=/var/lib/machines/$NAME
IMG=https://cloud-images.ubuntu.com/noble/current
TAR=/var/cache/trap/noble-server-cloudimg-amd64-root.tar.xz
NS=(systemd-nspawn -q --settings=false --register=no --resolv-conf=bind-uplink -D "$ROOT" --pipe --)
export DEBIAN_FRONTEND=noninteractive
dpkg -s systemd-container nftables >/dev/null 2>&1 || apt-get install -y -q systemd-container nftables >/dev/null

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
Address=10.201.$N.2/30
Gateway=10.201.$N.1
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

# farm 쪽: 컨테이너 veth 게이트웨이 + 바깥 포트 → 컨테이너
install -d /etc/systemd/nspawn /usr/local/lib/relay "/etc/systemd/system/systemd-nspawn@$NAME.service.d"
printf '[Exec]\nBoot=yes\nPrivateUsers=no\n[Network]\nVirtualEthernet=yes\n' > "/etc/systemd/nspawn/$NAME.nspawn"
# veth 주소는 networkd 설정으로 고정한다 — 스크립트로 넣으면 기본 80-container-ve.network가 다시 설정하며 지운다(11/22 경쟁)
cat > "/etc/systemd/network/10-ve-$NAME.network" <<EOF
[Match]
Name=ve-$NAME

[Network]
Address=10.201.$N.1/30
LinkLocalAddressing=no
IPv6AcceptRA=no
ConfigureWithoutCarrier=yes
EOF
systemctl enable --now systemd-networkd >/dev/null 2>&1 || true
networkctl reload 2>/dev/null || true
cat > "/usr/local/lib/relay/trap-$NAME-up" <<EOF
#!/bin/sh
sysctl -q -w net.ipv4.ip_forward=1
nft -f - <<NFT
table ip trap_$N
delete table ip trap_$N
table ip trap_$N {
  chain pre {
    type nat hook prerouting priority dstnat; policy accept;
    ip daddr $FARM tcp dport $EXT dnat to 10.201.$N.2:$INT
  }
}
NFT
EOF
chmod 755 "/usr/local/lib/relay/trap-$NAME-up"
printf '[Service]\nExecStartPost=/usr/local/lib/relay/trap-%s-up\n' "$NAME" > "/etc/systemd/system/systemd-nspawn@$NAME.service.d/relay.conf"
systemctl daemon-reload
systemctl enable "systemd-nspawn@$NAME" >/dev/null 2>&1
systemctl restart "systemd-nspawn@$NAME"
for i in $(seq 60); do systemd-run -M "$NAME" -q --wait -P systemctl is-system-running --wait >/dev/null 2>&1 && break; sleep 1; done
echo "trap $NAME($EDH) $SVC: $FARM:$EXT → 10.201.$N.2:$INT — $(systemd-run -M "$NAME" -q --wait -P sh -c "hostname; ss -Hltn | awk '{print \$4}' | tr '\n' ' '")"
