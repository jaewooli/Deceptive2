#!/usr/bin/env bash
# 시나리오 2 — 남은 장기 AWS 키 사용 (plan-wbs 5절, 커버리지 01-vendor-feature-map 6-1)
#
# 서사: S3 전환 때 정리 안 된 옛 IAM 사용자 backup-legacy의 장기 키가 app-01 postgres 계정 ~/.aws/credentials 에 남아 있다(T6).
#   공격자가 그 키를 찾아(호스트 1차) 쓴다(AWS 2차).
# 전제: 공격자가 app-01에 접근해 있다(초기 침투·측면 이동은 재현 안 함 — 탐지 대상 아님). 실제 무기는 쓰지 않는다.
#
# 단계 → ATT&CK → 탐지 기능:
#   키 열람  T1552.001   기능2 호스트 1차(미끼 파일 열람 감시 — auditd credential-location 규칙)  ← 로컬에서 재현
#   키 사용  T1078.004   기능2 CloudTrail 2차(AWS)  ← 11/28 AWS 구축 뒤. 로컬에선 키가 placeholder라 호출 안 함
#
# 로컬 한계: ~/.aws/credentials 는 로컬 랩 전용 키(placeholder) + EC2에선 IMDS가 먼저라 이 파일이 없을 수 있음(11/28 확인, HANDOFF 16).
#   그래서 로컬 리허설은 "키 열람" 관측치(호스트 1차 경보)만 만든다. 실제 AWS 호출(2차)은 11/28.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAB="$ROOT/infra/local-vm/lab.sh"

echo "[시나리오2] app-01 에서 backup-legacy 키 열람 (호스트 1차). AWS 2차(CloudTrail)는 11/28"
# 로그인 세션(auid 있음)으로 자격증명 파일을 읽는다 — A5/A6 백업 cron(auid unset)과 구별되는 "사람이 열었다"
timeout 60 "$LAB" ssh app-01 "sudo -u postgres -H bash -s" <<'SESSION'
set -u
echo "  키 열람 (T1552.001)"
grep -A2 backup-legacy ~/.aws/credentials >/dev/null 2>&1 || cat ~/.aws/credentials >/dev/null 2>&1 || true
sleep 3
# 키 사용(T1078.004)은 AWS에서만 — 로컬 placeholder 키로는 호출하지 않는다(네트워크·실제 자격증명 없음)
echo "  (키 사용은 11/28 AWS — aws sts get-caller-identity 로 CloudTrail 2차 검증)"
SESSION
echo "[시나리오2] 끝 — 호스트 1차 경보(감사, 파일=~postgres/.aws/credentials)를 run.sh 가 판정"
