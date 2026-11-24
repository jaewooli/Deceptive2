#!/usr/bin/env bash
# 정적 검사(배포 전, 서버 없이 몇 초) — 검사 3겹의 첫째(HANDOFF 5절). 실패하면 0이 아닌 값으로 끝난다
#   infra/checks/static.sh
set -uo pipefail
cd "$(dirname "$0")/../.."
fail=0
say() { printf "%s %s\n" "$1" "$2"; if [ "$1" = "✗" ]; then fail=1; fi; return 0; }

# 1. 환경 값은 infra/env/에만(docs/local-aws-parity.md 원칙 2): 서버·엔진 코드에 로컬 랩 주소가 박혀 있으면 실패(주석·테스트 제외)
hits=$(grep -rnE '10\.0\.(2|20|21)\.[0-9]+' servers baits forensics --include='*.sh' --include='*.py' --include='*.service' --include='*-up' --include='*-stop' \
  | grep -v '/tests/' | grep -vE '^[^:]+:[0-9]+:\s*#' | grep -vE '#.*10\.0\.' | grep -vE '^\S+\.py:[0-9]+:\s+(sudo |python3 )' || true)
[ -z "$hits" ] && say ✓ "환경 주소가 코드에 없음" || { say ✗ "환경 주소가 코드에 박힘:"; echo "$hits" | sed 's/^/    /'; }

# 2. 운영 서버에 올라가는 코드에 local 경로표 규칙 이동 금지(11/22 먹통 원인)
hits=$(grep -rnE 'ip rule (del|delete) .*pref 0|ip rule add .*lookup local' servers infra/local-vm || true)
[ -z "$hits" ] && say ✓ "local 규칙(pref 0)을 옮기는 코드 없음" || { say ✗ "local 규칙 이동:"; echo "$hits" | sed 's/^/    /'; }

# 2-1. nft 예약어를 체인 이름으로 쓰지 않기(11/23 두 번: `chain fwd`가 문법 오류 → 라우터 설정 실패, 팜 relay가 안 올라옴)
hits=$(grep -rnE 'chain (fwd|dup|tproxy|log|limit|reject|counter|queue|meta|ct) ' servers infra --include='*.sh' --include='*.py' || true)
[ -z "$hits" ] && say ✓ "nft 체인 이름에 예약어 없음" || { say ✗ "nft 예약어 체인 이름:"; echo "$hits" | sed 's/^/    /'; }

# 2-2. 서버에 남는 파일에 프로젝트 용어 금지(CLAUDE.md — 11/23: /opt/moa-notify 주석에 디코이·미끼·벤더 이름이 있어 공격자가 읽으면 끝)
#   남는 파일 = moa-notify 데몬·유닛, 공통 베이스가 설치하는 규칙·설정 파일, 웹 앱. 실행 뒤 지워지는 설치 스크립트는 제외
TERMS='미끼|디코이|트랩|투영|허니|기만|Illusive|Attivo|Acalvio|Zscaler|Smokescreen|Canary|[Dd]ecoy|[Bb]ait|[Hh]oney|[Dd]ecept|breadcrumb'
hits=$(git ls-files servers/detection/moa-notify/moa_notify.py servers/detection/moa-notify/moa-notify.service servers/detection/moa-notify/config.example.json \
  'servers/base/audit/*.rules' 'servers/base/ssh/*' 'servers/base/clamav/*' 'servers/base/cloudwatch/*' 'servers/base/postgresql/*' servers/webapp \
  | xargs grep -nE "$TERMS" 2>/dev/null || true)
[ -z "$hits" ] && say ✓ "서버에 남는 파일에 프로젝트 용어 없음" || { say ✗ "서버에 남는 파일에 프로젝트 용어:"; echo "$hits" | cut -c1-160 | sed 's/^/    /'; }

# 3. 셸 문법 + (있으면) shellcheck 오류 수준
for f in $(git ls-files '*.sh' servers/hosts/farm/guest/guest-up); do
  bash -n "$f" 2>/dev/null || say ✗ "문법: $f"
done
if command -v shellcheck >/dev/null; then
  out=$(git ls-files '*.sh' | xargs shellcheck -S error 2>&1) && say ✓ "shellcheck(오류 수준)" || { say ✗ "shellcheck:"; echo "$out" | head -20; }
else
  say "·" "shellcheck 없음(apt install shellcheck) — 건너뜀"
fi

# 4. 파이썬 문법 + 단위 테스트(미끼 엔진·블렌딩·moa-notify)
python3 -m py_compile $(git ls-files '*.py') 2>/dev/null && say ✓ "파이썬 문법" || say ✗ "파이썬 문법"
find . -name __pycache__ -not -path './.claude/*' -prune -exec rm -rf {} + 2>/dev/null
python3 -m unittest discover -s baits/tests -q 2>&1 | tail -1 | grep -q OK && say ✓ "단위 테스트: baits" || say ✗ "단위 테스트: baits"
(cd servers/detection/moa-notify && python3 -m unittest discover -s tests -q 2>&1 | tail -1 | grep -q OK) && say ✓ "단위 테스트: moa-notify" || say ✗ "단위 테스트: moa-notify"
find . -name __pycache__ -not -path './.claude/*' -prune -exec rm -rf {} + 2>/dev/null

# 5. 환경 프로필이 같은 키를 갖는가(로컬에만 있는 값 = AWS에서 빠지는 값)
python3 - <<'PY' && say ✓ "환경 프로필 키 일치(local·aws)" || say ✗ "환경 프로필 키 불일치"
import yaml, sys
a, b = (yaml.safe_load(open(f"infra/env/{n}.yml")) for n in ("local", "aws"))
def keys(d, p=""):
    return {p + k for k in d} | {x for k, v in d.items() if isinstance(v, dict) and k not in ("hosts", "segments") for x in keys(v, p + k + ".")}
d = keys(a) ^ keys(b)
d -= {"access.key", "access.transport", "farm.instance_type"}   # 접속 방식·인스턴스 타입은 환경마다 다른 키
if d: print("  다른 키:", sorted(d)); sys.exit(1)
PY
exit $fail
