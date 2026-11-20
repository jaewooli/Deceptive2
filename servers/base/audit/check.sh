#!/usr/bin/env bash
# audit 규칙이 빠짐없이 올라갔는지 확인한다. 읽기만 함, root로 실행.
#   기대 줄 수 = /etc/audit/rules.d/*.rules 의 -a/-w 줄
#                - 서버에 없는 디렉터리를 대상으로 한 규칙(-F dir=…)
#   실제 줄 수 = auditctl -l
# 다르면 종료 코드 1 (12-ignore-error 때문에 로드 오류가 조용히 넘어갈 수 있어서)
set -euo pipefail
shopt -s nullglob

expected=0
skipped=()
for f in /etc/audit/rules.d/*.rules; do
  while IFS= read -r line; do
    case "$line" in -a*|-w*) ;; *) continue ;; esac
    if [[ "$line" =~ -F[[:space:]]+dir=([^[:space:]]+) ]] && [ ! -d "${BASH_REMATCH[1]}" ]; then
      skipped+=("$(basename "$f"): ${BASH_REMATCH[1]} 없음")
      continue
    fi
    expected=$((expected + 1))
  done < "$f"
done

actual=$(auditctl -l | grep -c '^-[aw]' || true)

echo "audit 규칙: 기대 $expected, 실제 $actual"
for s in "${skipped[@]}"; do echo "  건너뜀(대상 없음): $s"; done
if [ "$actual" -ne "$expected" ]; then
  echo "불일치: 로드 중 오류로 빠진 규칙이 있음 (augenrules --load 출력 확인)" >&2
  exit 1
fi
