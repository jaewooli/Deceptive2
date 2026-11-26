#!/usr/bin/env bash
# 기준선 정상 작업 — app-01 (근거: scenarios/baseline/app-01.md A1~A14, plan-wbs 5절 "기준선(시간 압축 방식)")
#
# 48시간을 기다리지 않고, 정상 작업을 "48시간 상당 횟수"만큼 반복 실행해 오탐 기준선을 만든다(11/29 저녁).
# 11/30에 이 결과를 app-01.md 의 "예상 오탐"과 비교 → 오탐 낸 작업만 억제 규칙(12/1) → 미끼 유형별 자동 차단 판정.
#
# 원칙: 공격 행동은 넣지 않는다(정상 작업만). 각 작업은 app-01 역할에서 실제로 일어나는 것. 새 작업 범주는 안 만든다.
#   오탐의 핵심은 "모든 파일·호스트를 건드리는 자동화 도구"(백업·clamscan·nmap·grep)가 미끼 파일을 같이 읽는 것.
#
# 실행: scenarios/baseline/run-app-01.sh [배수]   (배수=1이 app-01.md 표의 48시간 상당 횟수. 시험은 배수를 줄여서)
#   무거운 작업(A9 clamscan·A10 nmap)은 BASELINE_HEAVY=1 일 때만 — 메모리·시간(11/22 OOM 주의).
#   결과: out/baseline/app-01.<타임스탬프>.log (작업별 시작·끝 시각 — 경보 수신기와 맞춰 오탐을 귀속)
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAB="$ROOT/infra/local-vm/lab.sh"
MULT="${1:-1}"
HEAVY="${BASELINE_HEAVY:-0}"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$ROOT/out/baseline"; mkdir -p "$OUT"
LOG="$OUT/app-01.$STAMP.log"
echo "# 기준선 app-01 배수=$MULT heavy=$HEAVY 시작 $(date -Is)" | tee "$LOG"

# app-01 에서 명령을 돌린다. 작업마다 시각을 로그에 남겨 경보를 작업에 귀속한다.
on(){ timeout 180 "$LAB" ssh app-01 "$@"; }
mark(){ echo "$(date -Is) $*" | tee -a "$LOG"; }
# 48시간 상당 횟수 × 배수 (app-01.md 표)
n(){ local base=$1; echo $(( base * MULT )); }

run_task(){ # 이름 횟수 '사용자' '명령'
  local name=$1 count=$2 user=$3 cmd=$4 i
  for ((i=1;i<=count;i++)); do
    mark "A:$name ($i/$count) user=$user"
    on "sudo -u $user -H bash -lc $(printf %q "$cmd")" >>"$LOG" 2>&1 || mark "  (비정상 종료 — 로그 참고)"
    sleep 1
  done
}

# A1 관리자 상태 확인 (ssm 세션 흉내 = ssm-user 없으면 ubuntu) — 오탐 없음 예상
run_task A1-status "$(n 4)" root 'df -h; free -m; systemctl status postgresql --no-pager | head -5; journalctl -u postgresql -n 5 --no-pager'
# A5 S3 백업 cron: pg_dump → gzip, 그리고 awscli가 IMDS보다 먼저 읽는 ~/.aws/credentials 열람(오탐원 T6). 실제 S3 전송은 로컬에서 생략
run_task A5-backup "$(n 2)" postgres 'pg_dump -Fc moayeyak 2>/dev/null | gzip -c >/tmp/moa-$$.dump.gz; ls -l /tmp/moa-$$.dump.gz; cat ~/.aws/credentials >/dev/null; rm -f /tmp/moa-$$.dump.gz'
# A6 관리자 백업 결과 확인: aws s3 ls (자격증명 읽음) — 로컬은 네트워크 없음, 자격증명 열람만 재현(로그인 세션 auid 있음)
run_task A6-s3ls "$(n 2)" root 'cat /var/lib/postgresql/.aws/credentials >/dev/null; echo "(aws s3 ls 는 11/28 AWS)"'
# A7 홈 디렉터리 백업: tar — 미끼 파일 내용을 읽음(오탐원 T6)
run_task A7-homebak "$(n 2)" root 'tar czf /var/backups/home-$$.tgz /home 2>/dev/null; ls -l /var/backups/home-$$.tgz; rm -f /var/backups/home-$$.tgz'
# A8 updatedb: 이름만 읽음 — 오탐 없을 것으로 예상(실측 대상)
run_task A8-updatedb "$(n 2)" root 'command -v updatedb >/dev/null && updatedb || echo "(plocate 없음)"'
# A11 개발자 grep -r password: 설정 확인 — credentials 파일을 엶(오탐원 T6)
run_task A11-grep "$(n 1)" postgres 'grep -rIl password ~ /etc /srv 2>/dev/null | head'
# A13 DB 정기 관리: vacuum/느린 쿼리 — 오탐 없음 예상
run_task A13-dbmaint "$(n 1)" postgres 'vacuumdb --analyze moayeyak 2>&1 | tail -2; psql -c "select count(*) from pg_stat_activity" 2>&1 | tail -3'

if [ "$HEAVY" = 1 ]; then
  # A9 ClamAV 전체 검사: 파일 내용 전부(오탐원 T6) — 메모리/시간 큼(11/22 OOM 주의, lab.sh 에서 디코이 검사용 2GB)
  run_task A9-clamscan "$(n 1)" root 'command -v clamscan >/dev/null && clamscan -r --infected /home /etc /srv /opt 2>&1 | tail -3 || echo "(clamav 없음)"'
  # A10 내부망 점검 nmap: 디코이 포트도 두드림 → 디코이 DB/sshd 경보 오탐 예상
  run_task A10-nmap "$(n 1)" root 'command -v nmap >/dev/null && nmap -sV --top-ports 50 10.0.20.0/24 2>&1 | tail -5 || echo "(nmap 없음)"'
else
  mark "A9-clamscan·A10-nmap 생략 (BASELINE_HEAVY=1 로 켠다)"
fi

echo "# 기준선 app-01 끝 $(date -Is)" | tee -a "$LOG"
echo "로그: $LOG — 11/30 에 app-01.md '예상 오탐'과 수신기 경보를 이 시각들로 맞춰 비교"
