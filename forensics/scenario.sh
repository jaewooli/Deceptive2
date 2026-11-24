#!/usr/bin/env bash
# 출발지 포렌식 회귀 시나리오 — 공격자 자리(web-01 deploy 셸 하나)에서 탐지 경로 다섯을 차례로 건드린다.
#   먼저 상관기를 켠다: python3 forensics/correlate.py watch   그다음: forensics/scenario.sh
# 보는 것(out/forensics/*/case.json·watch.log): 경로마다 P를 잡았나, 경보→P 시간, 같은 세션은 한 사건으로 합쳐지나, 세션 활동에 명령이 다 있나
# 순서가 뜻이 있다: 미끼 열람 전(①~③)엔 추적 중인 세션이 없어 짧은 연결의 P를 소켓만으로 잡아야 한다(tar-pit 판단 재료)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAB="$ROOT/infra/local-vm/lab.sh"
# 투영 디코이 주소는 환경 값에서(코드에 환경 주소 금지) — 렌더된 레지스트리·맥락
STG=$(cd "$ROOT/infra/checks" && "${CTL_PY:-$HOME/.cache/deceptive2-ctl/bin/python}" -c 'import paths; print(paths.variables()[0]["proj:stg:ip"])')
timeout 200 "$LAB" ssh web-01 "sudo -u deploy -H STG=$STG bash -s" >/dev/null 2>&1 <<'S'
cd ~
printf 'PING\r\n' | nc -w2 app-01 6379; sleep 8                                   # ① 트랩(app-01 빈 포트)
ssh -o BatchMode=yes -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no \
    -o ConnectTimeout=5 "$STG" true; sleep 8                                   # ② 투영 디코이(인증 실패로 바로 끝남)
PGCONNECT_TIMEOUT=5 psql "postgresql://postgres:postgres@db-backup-01:5432/postgres" -c 'select 1'; sleep 8   # ③ 디코이 PG 추측 접속
u=$(grep ^REPORT_DB_URL /srv/app/.env | cut -d= -f2- | sed 's/+psycopg//'); psql "$u" -c 'select 1'; sleep 8 # ④ T1 열람 → 미끼 계정
ssh -o BatchMode=yes db-backup-01 'sleep 15'; sleep 2                               # ⑤ T2 미끼 키로 디코이 로그인(머묾)
S
echo "끝 — out/forensics/ 확인"
