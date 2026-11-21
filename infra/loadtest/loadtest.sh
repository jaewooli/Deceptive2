#!/usr/bin/env bash
# 부하 테스트 (plan-wbs 6절 "11/22 필수 확인"). 대상 서버에서 root로, /tmp에 복사해 실행한다.
#   sudo bash /tmp/loadtest.sh <decoy|app|web> [초]   # 기본 300초
# 서버에 올라가는 코드가 아니다(servers/ 밖). 끝나면 만든 임시 파일·프로세스를 지우고 결과만 stdout에 낸다.
#
# 동시에 거는 부하
#   공통 : auditd execve(로그인 세션 명령 반복), ClamAV 전체 검사(clamscan, 기준선 정상 작업 5절)
#   decoy: sshd 추가 3개(IP별 sshd 대용 — 로컬엔 보조 IP가 없어 포트로 분리) + 4개 sshd에 로그인 실패 반복,
#          PostgreSQL 로그인 실패 반복(→ moa-notify 웹훅)
#   app  : PostgreSQL 로그인 실패 + pg_dump 반복
#   web  : nginx → gunicorn 요청 반복
set -uo pipefail
PROFILE=${1:?decoy|app|web}
DUR=${2:-300}
W=$(mktemp -d /tmp/lt.XXXX)
PIDS=()
cleanup() {
  for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done
  pkill -f "$W/" 2>/dev/null; pkill -x clamscan 2>/dev/null
  wait 2>/dev/null
  rm -rf "$W"
}
trap cleanup EXIT

# journald는 메모리 압박 중에 늦게 기록한다(1GiB에서 OOM을 0으로 셈) → 커널 링 버퍼를 직접 센다
oom_count() { dmesg | grep -c 'Out of memory: Killed process' ; }
OOM0=$(oom_count)

echo "== 호스트"
echo "profile=$PROFILE dur=${DUR}s kernel=$(uname -r) mem_total_mib=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo) swap_total_mib=$(awk '/SwapTotal/{print int($2/1024)}' /proc/meminfo) cpus=$(nproc)"
echo "== 에이전트 목록 (세 서버 동일해야 함)"
for u in auditd snap.amazon-ssm-agent.amazon-ssm-agent amazon-cloudwatch-agent clamav-freshclam unattended-upgrades cron; do
  printf '%-45s %s\n' "$u" "$(systemctl is-active "$u" 2>/dev/null)"
done
printf '%-45s %s\n' "amazon-ssm-agent(snap)" "$(snap list amazon-ssm-agent 2>/dev/null | awk 'NR==2{print $2}')"
printf '%-45s %s\n' "amazon-cloudwatch-agent(deb)" "$(dpkg-query -W -f='${Version}' amazon-cloudwatch-agent 2>/dev/null)"
printf '%-45s %s\n' "auditctl -l 줄 수" "$(auditctl -l | wc -l)"

# ---- 표본 수집: 1초마다 MemAvailable, 최저점에서 상위 프로세스 RSS
sampler() {
  local min=999999999 t=0 cmax=0
  while :; do
    local av c; av=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
    echo "$t $av" >> "$W/mem.tsv"
    c=$(ps -C clamscan -o rss= | awk '{s+=$1} END{print s+0}')
    [ "$c" -gt "$cmax" ] && { cmax=$c; echo "$cmax" > "$W/clam.maxrss"; }
    if [ "$av" -lt "$min" ]; then
      min=$av
      ps -eo rss=,comm= --sort=-rss | head -12 > "$W/top_at_min.txt"
    fi
    t=$((t + 1)); sleep 1
  done
}
sampler & PIDS+=($!)

ps -eo rss=,comm= --sort=-rss | head -12 > "$W/top_idle.txt"
AV_IDLE=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)

# ---- 공통 부하
cat > "$W/execloop.sh" <<'EOF'
while :; do for i in $(seq 50); do /bin/true; id >/dev/null; done; sleep 0.2; done
EOF
bash "$W/execloop.sh" & PIDS+=($!)

if [ -d /var/lib/clamav ] && ls /var/lib/clamav/*.c[lv]d >/dev/null 2>&1; then
  ( s=$SECONDS; clamscan -r -i --exclude-dir='^/(proc|sys|dev|run)' / > "$W/clam.out" 2>&1; echo "exit=$? 걸린시간=$((SECONDS - s))s" > "$W/clam.done" ) &
  PIDS+=($!)
  CLAM=started
else
  CLAM="시그니처 DB 없음(freshclam 미완) — 생략"
fi

# ---- 역할별 부하
case "$PROFILE" in
  decoy)
    install -d /run/sshd
    for n in 1 2 3; do
      sed -e '/^#\?Port /d' -e '/^#\?PidFile /d' /etc/ssh/sshd_config > "$W/sshd_$n.conf"
      printf 'Port 220%s\nPidFile %s/sshd_%s.pid\n' "$n" "$W" "$n" >> "$W/sshd_$n.conf"
      /usr/sbin/sshd -D -f "$W/sshd_$n.conf" & PIDS+=($!)
    done
    sleep 1
    cat > "$W/sshloop.sh" <<'EOF'
p=$1
while :; do
  for i in 1 2 3 4 5; do
    timeout 5 ssh -p "$p" -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -o PreferredAuthentications=publickey -o LogLevel=QUIET backup@127.0.0.1 true &
  done; wait; sleep 0.5
done
EOF
    for p in 22 2201 2202 2203; do bash "$W/sshloop.sh" "$p" & PIDS+=($!); done
    ;;
esac
case "$PROFILE" in
  decoy|app)
    cat > "$W/pgloop.sh" <<'EOF'
while :; do
  for u in report_ro sync_svc; do PGPASSWORD=x PGCONNECT_TIMEOUT=5 psql -h 127.0.0.1 -U "$u" -d postgres -c 'select 1' >/dev/null 2>&1 & done
  wait; sleep 0.3
done
EOF
    for i in 1 2 3 4; do bash "$W/pgloop.sh" & PIDS+=($!); done
    ;;
esac
if [ "$PROFILE" = app ]; then
  cat > "$W/dumploop.sh" <<'EOF'
while :; do runuser -u postgres -- pg_dumpall > /dev/null 2>&1; sleep 2; done
EOF
  bash "$W/dumploop.sh" & PIDS+=($!)
fi
if [ "$PROFILE" = web ]; then
  cat > "$W/webloop.sh" <<'EOF'
while :; do for i in $(seq 8); do curl -s -o /dev/null -m 10 http://127.0.0.1/ & curl -s -o /dev/null -m 10 http://127.0.0.1/stores & done; wait; done
EOF
  for i in 1 2; do bash "$W/webloop.sh" & PIDS+=($!); done
fi

sleep "$DUR"

# ---- 결과
OOM1=$(oom_count)
echo "== 결과"
awk -v idle="$AV_IDLE" 'BEGIN{min=1e12} {if($2<min){min=$2;at=$1}} END{printf "MemAvailable idle=%d MiB  최저=%d MiB (t=%ds)\n", idle, min/1024, at}' "$W/mem.tsv"
echo "OOM 커널 메시지: 테스트 전 $OOM0 → 후 $OOM1"
echo "ClamAV: $CLAM"
[ -f "$W/clam.maxrss" ] && echo "  clamscan 최대 RSS=$(( $(cat "$W/clam.maxrss") / 1024 )) MiB"
if [ -f "$W/clam.done" ]; then echo "  $(cat "$W/clam.done")"; grep -iE 'killed|error' "$W/clam.out" | head -3
elif [ "$CLAM" = started ]; then echo "  ${DUR}초 안에 안 끝남(검사 중)"; fi
echo "-- 유휴 시 상위 RSS(KiB)"; cat "$W/top_idle.txt"
echo "-- MemAvailable 최저 시점 상위 RSS(KiB)"; cat "$W/top_at_min.txt"
echo "-- 서비스 상태(테스트 후)"
for u in auditd snap.amazon-ssm-agent.amazon-ssm-agent amazon-cloudwatch-agent postgresql@16-main moa-notify nginx moayeyak ssh; do
  systemctl cat "$u" >/dev/null 2>&1 && printf '%-45s %s\n' "$u" "$(systemctl is-active "$u")"
done
dmesg | grep 'Out of memory: Killed process' | tail -5
