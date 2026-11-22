#!/usr/bin/env bash
# 로컬 전용: router VM = VPC 라우터 흉내. int(enp0s3, 10.0.20.1)와 pub(enp0s8, 10.0.21.1) 사이만 포워딩(NAT 없음, 바깥으로는 안 감)
# AWS VPC의 암묵적 라우터는 서브넷 사이에서 TTL을 줄이지 않는다(traceroute 1홉) → 포워딩할 때 TTL +1로 되돌려 같게
#   infra/local-vm/lab.sh run router infra/local-vm router.sh
set -euo pipefail
cat > /etc/netplan/61-lan-pub.yaml <<'Y'
network:
  version: 2
  ethernets:
    enp0s8:
      dhcp4: false
      addresses: [10.0.21.1/24]
Y
chmod 600 /etc/netplan/61-lan-pub.yaml
cat > /etc/sysctl.d/60-router.conf <<'S'
net.ipv4.ip_forward = 1
S
sysctl -q -p /etc/sysctl.d/60-router.conf
netplan apply
nft -f - <<'N'
table ip vpc
delete table ip vpc
table ip vpc {
  chain between {
    type filter hook forward priority filter; policy drop;
    iifname { "enp0s3", "enp0s8" } oifname { "enp0s3", "enp0s8" } accept
  }
}
N
iptables -w -t mangle -C PREROUTING -i enp0s3 -d 10.0.21.0/24 -j TTL --ttl-inc 1 2>/dev/null || iptables -w -t mangle -A PREROUTING -i enp0s3 -d 10.0.21.0/24 -j TTL --ttl-inc 1
iptables -w -t mangle -C PREROUTING -i enp0s8 -d 10.0.20.0/24 -j TTL --ttl-inc 1 2>/dev/null || iptables -w -t mangle -A PREROUTING -i enp0s8 -d 10.0.20.0/24 -j TTL --ttl-inc 1
# 재부팅 뒤에도: nft·iptables 규칙을 다시 거는 유닛
[ "$0" = /usr/local/sbin/lab-router ] || install -m 0755 "$0" /usr/local/sbin/lab-router
cat > /etc/systemd/system/lab-router.service <<'U'
[Unit]
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/lab-router
[Install]
WantedBy=multi-user.target
U
[ "$0" = /usr/local/sbin/lab-router ] || { systemctl daemon-reload; systemctl enable -q lab-router; }
ip -br addr show enp0s8
