#!/usr/bin/env bash
# 시나리오 3 — 관측된 봇 행동 안전 재현 (plan-wbs 5절, 커버리지 01-vendor-feature-map 6-1·6-2)
#
# 직전 Cowrie 허니팟에서 관측한 봇 체인을 "안전하게" 재현한다: 실제 멀웨어·크리덴셜 덤퍼는 쓰지 않고,
#   탐지가 보는 관측치(반입 파일·만든 파일·지속성 쓰기·삭제)만 무해한 내용으로 만든다.
# 봇은 유출된 미끼 키로 디코이(db-backup-01)에 backup 계정으로 로그인한다(unprivileged — 진짜 서버가 아니라 디코이).
#
# 단계 → ATT&CK → 탐지 기능:
#   반입     T1105            기능3·4  (SFTP로 무해한 표식 파일 업로드 → engagement가 파일 내용/해시 회수)
#   실행·숨김 T1059.004/T1564.001  기능3   (숨김 디렉터리에서 무해한 스크립트 실행 — 파일 하나 touch)
#   지속성   T1098.004(ssh키)·T1546.004(셸 시작 파일)  기능3 P0 결과 기반 감시
#   자격증명 덤프 T1003.008   기능3   (/etc/shadow 읽기 — backup은 거부됨, 시도만 engagement에 기록)
#   흔적 삭제 T1070.004       기능3   (반입 파일 삭제)
# 루트 권한이 필요한 지속성(ld.so.preload·cron.d, T1574.006/T1053.003)은 unprivileged 봇이 디코이에서 못 쓴다 →
#   시도는 engagement에 남지만 쓰기는 안 됨. 그 경로의 P0 감시(쓰기 경보)는 infra/checks/detect.py 가 진짜 서버에서 검증.
#
# 디코이에 남는 것은 run.sh(또는 이 스크립트 끝)에서 되돌린다 — 디코이를 깨지 않는다.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAB="$ROOT/infra/local-vm/lab.sh"

BOTKEY="$(cat <<'K'
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB0tESTtESTtESTtESTtESTtESTtESTtESTtESTtbot moabot@rehearsal
K
)"

echo "[시나리오3] 디코이 db-backup-01 에 미끼 키(backup)로 로그인한 봇 세션 재현"
# web-01 deploy 셸을 거쳐(미끼 ssh 별칭) 디코이로 — 실제 봇이 유출 키로 들어오는 경로와 같게
timeout 180 "$LAB" ssh web-01 "sudo -u deploy -H BOTKEY=$(printf %q "$BOTKEY") bash -s" <<SESSION
set -u
# 무해한 표식 파일을 로컬에서 만들어 SFTP로 디코이에 반입(T1105)
tmp=\$(mktemp)
printf 'REHEARSAL-ONLY benign marker %s\n' "\$(date -Is)" > "\$tmp"
sftp -b - -o BatchMode=yes db-backup-01 >/dev/null 2>&1 <<SFTP || true
-mkdir /tmp/.sess
put \$tmp /tmp/.sess/payload.bin
SFTP
rm -f "\$tmp"

# 봇 playbook을 한 세션으로 실행(engagement가 명령·만든 파일을 회수)
ssh -o BatchMode=yes -o ConnectTimeout=8 db-backup-01 "BOTKEY='\$BOTKEY' bash -s" <<'BOT' >/dev/null 2>&1 || true
set +e
cd /tmp/.sess 2>/dev/null || cd /tmp
chmod +x payload.bin 2>/dev/null
./payload.bin 2>/dev/null; sh -c 'touch /tmp/.sess/.done' 2>/dev/null   # 실행·숨김(T1059.004/T1564.001)
# 지속성: 내 authorized_keys(T1098.004) + 셸 시작 파일(T1546.004) — backup이 쓸 수 있는 것
mkdir -p ~/.ssh && chmod 700 ~/.ssh
printf '%s\n' "$BOTKEY" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
printf '# rehearsal\n' >> ~/.bashrc
# 루트 지속성 시도(ld.so.preload·cron) — unprivileged라 거부됨(sudo -n: 비밀번호 대기 없이 즉시 실패), 시도만 기록됨
echo '/tmp/.sess/payload.bin' | sudo -n tee /etc/ld.so.preload 2>/dev/null
echo '* * * * * root /tmp/.sess/payload.bin' | sudo -n tee /etc/cron.d/moabot 2>/dev/null
cat /etc/shadow 2>/dev/null >/dev/null        # 자격증명 덤프 시도(T1003.008) — 거부
sleep 10
# 흔적 삭제(T1070.004)
rm -rf /tmp/.sess 2>/dev/null
BOT
echo "  봇 세션 끝"
SESSION

echo "[시나리오3] 되돌리기 (디코이 정리 — authorized_keys·bashrc 미끼 줄 제거)"
timeout 60 "$LAB" ssh db-backup-01 "sudo -u backup -H bash -s" <<'CLEAN' 2>&1 | sed 's/^/  /' || true
set +e
# 리허설이 넣은 줄만 제거(backup authorized_keys 에서 moabot 줄, bashrc 의 rehearsal 줄)
[ -f ~/.ssh/authorized_keys ] && sed -i '/moabot@rehearsal/d' ~/.ssh/authorized_keys
[ -f ~/.bashrc ] && sed -i '/^# rehearsal$/d' ~/.bashrc
rm -rf /tmp/.sess
echo "정리 완료"
CLEAN
echo "[시나리오3] 끝 — engagement 세션 기록·P0 authorized_keys 경보를 run.sh 가 판정"
