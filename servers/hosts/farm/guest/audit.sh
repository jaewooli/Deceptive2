#!/usr/bin/env bash
# 디코이 감사 규칙 = 회사 서버와 같은 규칙(servers/base/audit — 지속성 경로 + 이 디코이 계정·서비스에서 만든 자격증명 파일 규칙, 11/26).
# 계정은 역할 단계에서 생기므로 역할 뒤에 다시 만든다. guest.sh offline 뒤 마운트된 디스크에(부팅 때 auditd가 rules.d를 읽음)
#   sudo ./audit.sh <이름> <base 디렉터리>
set -euo pipefail
n=${1:?이름}; b=${2:?base 디렉터리}
R=/var/lib/machines/$n
findmnt -rno SOURCE "$R" >/dev/null || { echo "$R 가 마운트돼 있지 않음" >&2; exit 2; }
# 저장소 규칙 전부(첫 부팅의 base/install.sh 뒤에 바뀐 규칙도 디코이에 닿게 — 11/26: 11/24 user-file 규칙이 디코이에 안 들어가 inside 검사 차이)
for f in 50-user-cmd.rules 60-persistence.rules 70-user-files.rules; do install -m 0640 "$b/audit/$f" "$R/etc/audit/rules.d/$f"; done
rm -f "$R/etc/audit/rules.d/55-user-files.rules"
t=$(mktemp); bash "$b/audit/account-rules.sh" "$R" > "$t"
install -m 0640 "$t" "$R/etc/audit/rules.d/61-account-files.rules"; rm -f "$t"
echo "감사 규칙: $n ($(grep -c '^-a' "$R/etc/audit/rules.d/61-account-files.rules")줄)"
