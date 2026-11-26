#!/usr/bin/env bash
# 시나리오 1 — 웹 침투 → 자격증명 탐색 → 디코이로 횡적 이동 → 미끼 DB 계정 (plan-wbs 5절, 커버리지 01-vendor-feature-map 6-1)
#
# 이 스크립트는 "공격자가 하는 일"이 아니라 "탐지가 보는 관측치"를 평범한 명령으로 만든다(리허설·회귀 테스트).
#   초기 침투(T1190, web-01 영수증 PDF RCE)는 커버리지 표에서 "탐지 대상 아님(전제)"이라 재현하지 않는다.
#   전제: 공격자가 web-01에서 deploy 셸 하나를 얻었다(forensics/scenario.sh와 같은 출발점). 실제 익스플로잇·무기는 쓰지 않는다.
#
# 단계 → ATT&CK → 탐지 기능(01-vendor-feature-map 6-1):
#   ② 자격증명 탐색   T1552.001/.004  기능2 미끼 파일 열람 감시(호스트)
#   ③ 내부 정찰       T1018/T1046     기능1 디코이 포트 접속(목적지) + Attivo 연결 테이블 미끼
#   ④ 디코이로 SSH    T1021.004/T1078 기능1·2 미끼 계정 로그인(목적지)
#   ⑤ 디코이 내 정찰  T1497/T1518     기능4 로그인 경보에 세션 명령 첨부(engagement)
#   ⑥ 미끼 DB 계정    T1078           기능2 더미 DB 리스너(목적지)
# 묶음: forensics/correlate.py(출발지 포렌식) + forensics/chain.py(침투 체인) → 한 체인, 미끼 ID로 털린 위치(web-01).
#
# 실행: scenarios/run.sh 1   (상관기를 켜고 돌린 뒤 체인·경보를 판정한다). 직접 돌리려면 먼저 correlate.py watch를 켠다.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAB="$ROOT/infra/local-vm/lab.sh"
CTL="${CTL_PY:-$HOME/.cache/deceptive2-ctl/bin/python}"
# 투영 디코이 주소는 환경 값에서(코드에 환경 주소 금지)
STG=$(cd "$ROOT/infra/checks" && "$CTL" -c 'import paths; print(paths.variables()[0]["proj:stg:ip"])')

echo "[시나리오1] web-01 deploy 셸에서 시작 (초기 침투 T1190은 전제 — 재현 안 함)"
# 한 로그인 세션(auditd ses) 안에서 전부 실행해야 체인이 한 공격자로 묶인다. STG만 넘긴다.
timeout 240 "$LAB" ssh web-01 "sudo -u deploy -H STG=$STG bash -s" <<'SESSION'
set -u
cd ~
sl(){ sleep "${1:-6}"; }   # 짧은 연결은 수집기가 소켓을 잡을 틈이 필요(tar-pit 판단 재료)

echo "  ② 자격증명 탐색 (T1552) — 미끼 파일 열람"
cat /srv/app/.env            >/dev/null; sl 4   # T1 REPORT_DB_URL(rpt_ro) + cache_hint(app-01:6379)
cat ~/.ssh/config            >/dev/null         # T2 미끼 키로 가는 ssh 별칭
cat ~/.ssh/id_ed25519_backup >/dev/null; sl 4   # T2 미끼 키 A
tail -n 40 ~/.bash_history   >/dev/null; sl 2   # T3 히스토리(T2로 유도)
ssh-add -l                   >/dev/null 2>&1 || true   # T4 ssh-agent 미끼 키 B(있으면)
systemctl cat report-sync    >/dev/null 2>&1 || cat /etc/systemd/system/report-sync.service >/dev/null 2>&1   # T5 sync_svc
sl 4

echo "  ③ 내부 정찰 (T1018/T1046) — 연결 테이블 + 디코이 포트"
ss -tanp 2>/dev/null | grep -E '5432|6379' >/dev/null || true   # Attivo: report-sync의 핸드셰이크 연결이 보임
ip neigh 2>/dev/null >/dev/null || true
printf 'PING\r\n' | nc -w2 app-01 6379 >/dev/null 2>&1 || true   # 기능1 트랩(app-01 빈 포트 → 팜 트랩)
sl 8

echo "  ④ 디코이로 SSH 이동 (T1021.004/T1078) — 미끼 키로 backup@db-backup-01"
# ⑤ 디코이 내 판별·정찰 명령(T1497/T1518)을 같은 로그인으로 — engagement가 세션 명령을 첨부
# -n: 이 ssh가 heredoc으로 들어오는 나머지 스크립트(⑥·투영)를 stdin으로 삼키지 않게 한다
ssh -n -o BatchMode=yes -o ConnectTimeout=8 db-backup-01 \
    'uname -a; systemd-detect-virt; cat /etc/os-release; dpkg -l 2>/dev/null | wc -l; ls -la /backup 2>/dev/null; sleep 12' >/dev/null 2>&1 || true
sl 4

echo "  ⑥ 미끼 DB 계정 사용 (T1078) — .env의 REPORT_DB_URL로 디코이 5432"
u=$(grep ^REPORT_DB_URL /srv/app/.env | cut -d= -f2- | sed 's/+psycopg//')
PGCONNECT_TIMEOUT=6 psql "$u" -c 'select 1' >/dev/null 2>&1 || true   # 미끼 계정 → 디코이 PG 접속 경보(관문 + tar-pit)
sl 6

echo "  (투영 디코이도 한 번 건드린다 — Acalvio 목적지 탐지)"
ssh -n -o BatchMode=yes -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no \
    -o ConnectTimeout=8 "$STG" true >/dev/null 2>&1 || true
sl 4
echo "  세션 끝"
SESSION
echo "[시나리오1] 끝 — 경보·체인은 scenarios/run.sh 가 판정 (out/scenarios/, out/chains/, out/forensics/)"
