#!/usr/bin/env bash
# db-backup-01 보조 사설 IP와 IP별 서비스. root로, 역할 install.sh 다음에 실행. 여러 번 실행해도 결과가 같다.
#   sudo ./addresses.sh <주 IP> <보조1> <보조2> <보조3>
# 목적: 넓이 — 한 인스턴스가 스캔에서 여러 대로 보이게(docs/plan-wbs.md 3절 기능 1, 01-vendor-feature-map 문제 2)
#   IP마다 별도 sshd + 별도 호스트 키(같은 키면 스캔 한 번에 "한 대"로 묶임), 포트 조합이 다름
#   SSH 버전 문자열은 그대로 — 이 회사 서버는 같은 24.04·같은 패치라 같은 게 주변과 섞인다
#   주 IP  : 22 + 5432 / 보조1: 22 / 보조2: 22 + 5432 / 보조3: 22
# 로그인한 뒤에는 hostname·프로세스가 같다(한계, 측정 대상). 주소는 재시작해도 그대로(ENI 사설 IP)
set -euo pipefail
PRIMARY=${1:?주 IP}; shift
[ $# -eq 3 ] || { echo "보조 IP 3개" >&2; exit 2; }
SECONDARY=("$@")
PG_ON=("$PRIMARY" "${SECONDARY[1]}")
KEYS_WHEN=${KEYS_WHEN:-"2024-06-12 14:21:37"}   # 옮겨 온 호스트 키 시각(base hostkeys와 같게)

# ---- 보조 IP: 기본 netplan(cloud-init)의 인터페이스에 주소만 더한다
IFACE=$(ip -4 route show default | awk '{print $5; exit}')
PREFIX=$(ip -4 -o addr show dev "$IFACE" | awk -v p="$PRIMARY" '$4 ~ "^"p"/" {split($4, a, "/"); print a[2]}')
[ -n "$PREFIX" ] || { echo "$IFACE에 주 IP $PRIMARY 없음" >&2; exit 1; }
{
  echo "network:"
  echo "  version: 2"
  echo "  ethernets:"
  echo "    $IFACE:"
  echo "      addresses:"
  for ip in "${SECONDARY[@]}"; do echo "        - $ip/$PREFIX"; done
} > /etc/netplan/60-secondary.yaml
chmod 600 /etc/netplan/60-secondary.yaml
netplan apply

# ---- 주 sshd: 소켓만 주 IP로 좁힌다(sshd_config는 그대로 — app-01과 같은 파일)
install -d /etc/systemd/system/ssh.socket.d
printf '[Socket]\nListenStream=\nListenStream=%s:22\n' "$PRIMARY" > /etc/systemd/system/ssh.socket.d/listen.conf

# ---- 보조 IP별 sshd
cat > /etc/systemd/system/ssh-addr@.service <<'EOF'
[Unit]
Description=OpenBSD Secure Shell server on %i
After=network-online.target auditd.service
Wants=network-online.target

[Service]
ExecStartPre=/usr/bin/mkdir -p -m 0755 /run/sshd
ExecStartPre=/usr/sbin/sshd -t -f /etc/ssh/addr/%i/sshd_config
ExecStart=/usr/sbin/sshd -D -f /etc/ssh/addr/%i/sshd_config
ExecReload=/bin/kill -HUP $MAINPID
KillMode=process
Restart=on-failure
RuntimeDirectory=sshd-%i

[Install]
WantedBy=multi-user.target
EOF
for ip in "${SECONDARY[@]}"; do
  d=/etc/ssh/addr/$ip
  install -d -m 0755 "$d"
  for t in rsa ecdsa ed25519; do
    [ -f "$d/ssh_host_${t}_key" ] || ssh-keygen -q -t "$t" -N "" -C "root@$(hostname)" -f "$d/ssh_host_${t}_key"
  done
  cat > "$d/sshd_config" <<EOF
ListenAddress $ip:22
HostKey $d/ssh_host_rsa_key
HostKey $d/ssh_host_ecdsa_key
HostKey $d/ssh_host_ed25519_key
PidFile /run/sshd-$ip/sshd.pid
Include /etc/ssh/sshd_config
EOF
  touch -h -d "$KEYS_WHEN" "$d"/ssh_host_*
done
systemctl daemon-reload
systemctl restart ssh.socket
systemctl restart ssh.service 2>/dev/null || true
for ip in "${SECONDARY[@]}"; do systemctl enable --now "ssh-addr@$ip.service"; systemctl restart "ssh-addr@$ip.service"; done

# ---- PG: 주 IP와 보조2에만
conf_d=$(ls -d /etc/postgresql/*/main/conf.d | head -1)
printf "# 역할: 이 서버의 DB 주소\nlisten_addresses = 'localhost,%s'\n" "$(IFS=,; echo "${PG_ON[*]}")" > "$conf_d/60-listen.conf"
chown postgres:postgres "$conf_d/60-listen.conf"
systemctl restart postgresql

ss -Hltn | awk '{print $4}' | sort -u
