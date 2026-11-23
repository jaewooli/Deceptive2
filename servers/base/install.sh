#!/usr/bin/env bash
# 공통 서버 설정. root로 실행, 여러 번 실행해도 결과가 같다.
#   sudo ./install.sh            # 공통 패키지·audit 규칙
#   sudo ./install.sh postgresql # PostgreSQL이 설치된 서버에서 공통 PG 설정
# CWAGENT_MODE: EC2에서는 ec2(기본). 로컬 VM에서는 onPremise(리전은 agent.json에 고정, 자격증명 없음 → 전송만 실패)
set -euo pipefail
cd "$(dirname "$0")"

AUDIT_EXAMPLES=/usr/share/doc/auditd/examples/rules
# 12-ignore-error: 30-stig의 /etc/NetworkManager/ 규칙은 이 디렉터리가 없는 서버에서 로드 오류를 내고
# 그 뒤 규칙을 모두 건너뛴다. 오류 줄만 건너뛰고 계속 로드한다
AUDIT_FROM_EXAMPLES=(10-base-config.rules 12-ignore-error.rules 30-stig.rules 43-module-load.rules)

# CloudWatch 에이전트: 서울 리전 버킷(내부 서버는 S3 게이트웨이 엔드포인트로 받음), AWS 서명 키로 검증
CWAGENT_URL=https://amazoncloudwatch-agent-ap-northeast-2.s3.ap-northeast-2.amazonaws.com/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
CWAGENT_KEY_URL=https://amazoncloudwatch-agent.s3.amazonaws.com/assets/amazon-cloudwatch-agent.gpg
CWAGENT_KEY_FPR=937616F3450B7D806CBD9725D58167303B789C72
CWAGENT_DIR=/opt/aws/amazon-cloudwatch-agent

base() {
  timedatectl set-timezone Asia/Seoul
  # rsyslog는 시작할 때의 시간대로 계속 쓴다 → 재시작하지 않으면 auth.log에 UTC(+00:00)와 KST가 섞인다
  systemctl restart rsyslog
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
  systemctl enable --now auditd
  augenrules --load
  audit/check.sh

  systemctl enable --now unattended-upgrades cron logrotate.timer
  systemctl enable --now clamav-freshclam || true
  # 정기 전체 검사: 백신을 깔아 두고 검사를 안 하는 서버는 앞뒤가 안 맞는다. 세 서버 같은 파일
  install -m 0644 clamav/clamav-scan.cron /etc/cron.d/clamav-scan
  install -m 0644 clamav/clamav-scan.logrotate /etc/logrotate.d/clamav-scan

  # networkd는 기본값으로 자기가 만들지 않은 경로·정책 규칙을 지운다(재시작·업데이트 때). 세 서버 공통(차이를 만들지 않음)
  install -d /etc/systemd/networkd.conf.d
  printf '[Network]\nManageForeignRoutingPolicyRules=no\nManageForeignRoutes=no\n' > /etc/systemd/networkd.conf.d/10-keep-foreign.conf

  ssh
  agents
}

# sshd 로그 수준(세 서버 공통 — 디코이만 다르면 단서). sshd는 같은 항목의 처음 값을 쓰고, 조각은 본문 앞에서 읽힌다
ssh() {
  install -m 0644 ssh/50-loglevel.conf /etc/ssh/sshd_config.d/50-loglevel.conf
  sshd -t && systemctl reload ssh
}

# 관리·로그 에이전트 2종. 세 서버 같은 설정 한 벌(변경 A)
agents() {
  # SSM 에이전트: Ubuntu EC2 AMI에는 snap으로 기본 설치돼 있다. 없는 경우(로컬 VM)만 같은 snap으로 설치
  snap list amazon-ssm-agent >/dev/null 2>&1 || snap install amazon-ssm-agent --classic

  if ! dpkg -s amazon-cloudwatch-agent >/dev/null 2>&1; then
    local t; t=$(mktemp -d)
    curl -fsSL -o "$t/a.deb" "$CWAGENT_URL"
    curl -fsSL -o "$t/a.deb.sig" "$CWAGENT_URL.sig"
    curl -fsSL -o "$t/key.gpg" "$CWAGENT_KEY_URL"
    export GNUPGHOME="$t/gnupg"; install -d -m 0700 "$GNUPGHOME"
    gpg -q --import "$t/key.gpg"
    gpg --with-colons --fingerprint | grep -q "^fpr:::::::::$CWAGENT_KEY_FPR:" || { echo "CloudWatch 에이전트 키 지문 불일치" >&2; exit 1; }
    gpg -q --verify "$t/a.deb.sig" "$t/a.deb"
    unset GNUPGHOME
    dpkg -i -E "$t/a.deb"
    rm -rf "$t"
  fi
  install -m 0644 cloudwatch/agent.json "$CWAGENT_DIR/etc/agent.json"
  "$CWAGENT_DIR/bin/amazon-cloudwatch-agent-ctl" -a fetch-config -m "${CWAGENT_MODE:-ec2}" -s -c "file:$CWAGENT_DIR/etc/agent.json"
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

# 재구축 때 옛 서버의 SSH 호스트 키를 함께 옮긴 상태(02-infra 4절, 세 서버 공통): 키 파일 시각을 첫 구축 시각으로
#   sudo ./install.sh hostkeys "2024-06-12 14:21:37"
hostkeys() {
  local when=${1:?첫 구축 시각}
  for f in /etc/ssh/ssh_host_*; do touch -h -d "$when" "$f"; done
}

case "${1:-base}" in
  base) base ;;
  agents) agents ;;
  ssh) ssh ;;
  postgresql) postgresql ;;
  hostkeys) hostkeys "${2:-}" ;;
  *) echo "사용법: $0 [base|agents|ssh|postgresql|hostkeys <시각>]" >&2; exit 2 ;;
esac
