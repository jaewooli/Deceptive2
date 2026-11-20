#!/usr/bin/env bash
# 공통 서버 설정. root로 실행, 여러 번 실행해도 결과가 같다.
#   sudo ./install.sh            # 공통 패키지·audit 규칙
#   sudo ./install.sh postgresql # PostgreSQL이 설치된 서버에서 공통 PG 설정
set -euo pipefail
cd "$(dirname "$0")"

AUDIT_EXAMPLES=/usr/share/doc/auditd/examples/rules
# 12-ignore-error: 30-stig의 /etc/NetworkManager/ 규칙은 이 디렉터리가 없는 서버에서 로드 오류를 내고
# 그 뒤 규칙을 모두 건너뛴다. 오류 줄만 건너뛰고 계속 로드한다
AUDIT_FROM_EXAMPLES=(10-base-config.rules 12-ignore-error.rules 30-stig.rules 43-module-load.rules)

base() {
  timedatectl set-timezone Asia/Seoul
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q
  apt-get install -y -q auditd clamav unattended-upgrades logrotate cron

  # audit 규칙: 배포판 예제 + 로그인 세션 명령 기록
  for f in "${AUDIT_FROM_EXAMPLES[@]}"; do
    test -f "$AUDIT_EXAMPLES/$f" || { echo "없음: $AUDIT_EXAMPLES/$f" >&2; exit 1; }
    install -m 0640 "$AUDIT_EXAMPLES/$f" "/etc/audit/rules.d/$f"
  done
  install -m 0640 audit/50-user-cmd.rules /etc/audit/rules.d/50-user-cmd.rules
  # 패키지 기본 audit.rules는 10-base-config와 같은 내용이고, 이름순으로 맨 뒤에 읽혀 -D로 앞 규칙을 지운다
  rm -f /etc/audit/rules.d/audit.rules
  augenrules --load
  systemctl enable --now auditd

  systemctl enable --now unattended-upgrades cron logrotate.timer
  systemctl enable --now clamav-freshclam || true
}

postgresql() {
  local conf_d
  conf_d=$(ls -d /etc/postgresql/*/main/conf.d | head -1)
  install -m 0644 -o postgres -g postgres postgresql/50-logging.conf "$conf_d/50-logging.conf"
  install -m 0644 -o postgres -g postgres postgresql/50-listen.conf "$conf_d/50-listen.conf"
  local hba="${conf_d%/conf.d}/pg_hba.conf"
  local line="host    all             all             10.0.0.0/16             scram-sha-256"
  grep -qxF "$line" "$hba" || echo "$line" >> "$hba"
  systemctl restart postgresql
}

case "${1:-base}" in
  base) base ;;
  postgresql) postgresql ;;
  *) echo "사용법: $0 [base|postgresql]" >&2; exit 2 ;;
esac
