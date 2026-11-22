#!/usr/bin/env bash
# 로컬 랩: farm 디코이 VM(servers/hosts/farm/guest/guest.sh) 만들기·역할 적용 — 제어 쪽. 서버에 남는 파일 없음(lab.sh run은 임시 경로 후 삭제)
#   infra/local-vm/farm-guest.sh create <이름>   # 1단계: 디스크 + 첫 부팅(패치·패키지·공통 베이스), 스스로 꺼짐 — 10~20분
#   infra/local-vm/farm-guest.sh role <이름>     # 2·3단계: offline → <이름>/role.sh → user-data 정리 → online
# 디코이 정의(아래 표). MAC = 그 디코이를 투영하는 센서 NIC의 MAC(디코이 안 `ip link` = 이웃 ARP 값, 11/23 HANDOFF 9절)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
LAB="$ROOT/infra/local-vm/lab.sh"
DIR=${VM_DIR:-$HOME/.cache/deceptive2-vm}
FARM="$ROOT/servers/hosts/farm"

# 이름   주소/접두       게이트웨이  MAC                메모리 vCPU 패키지                                  pg
TABLE="
stg-01  10.0.20.30/24  10.0.20.1  52:54:00:20:00:30  768    2    nginx,postgresql-16,python3-venv,git    pg
"
row() { awk -v n="$1" '$1==n' <<<"$TABLE"; }

cmd=${1:?create|role}; n=${2:?이름}
read -r name addr gw mac mem cpus pkgs pg <<<"$(row "$n")"
[ -n "${name:-}" ] || { echo "모르는 디코이: $n" >&2; exit 2; }
t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
cp -a "$FARM/guest" "$t/guest"; cp -a "$ROOT/servers/base" "$t/guest/base"; rm -rf "$t/guest/base/README.md"
cp "$DIR/id_ed25519.pub" "$t/mgmt.pub"     # 로컬 진짜 VM과 같은 관리 키(EC2 키 페어 자리)

case "$cmd" in
  create)
    printf 'set -euo pipefail\ncd "$(dirname "$0")"\nguest/guest.sh create %q %q %q %q %q %q %q mgmt.pub %q\n' \
      "$name" "$addr" "$gw" "$mac" "$mem" "$cpus" "$pkgs" "${pg/-/}" > "$t/run.sh"
    "$LAB" run farm "$t" run.sh ;;
  role)
    cp -a "$FARM/roles/${n%%-*}" "$t/role"
    args=()
    case "$n" in
      stg-01)   # 배포 묶음 = role/ 자신: app/(2025-05-12까지 이력), base/postgresql, carryover/, db-backup-01 호스트 키
        python3 "$ROOT/servers/webapp-history/build_history.py" --out "$t/role/app" --until 12 >/dev/null
        install -d "$t/role/base" "$t/role/carryover"
        cp -a "$ROOT/servers/base/postgresql" "$t/role/base/"
        cp "$ROOT/servers/hosts/db-backup-01/carryover/make_carryover.py" "$t/role/carryover/"
        "$LAB" ssh db-backup-01 'cat /etc/ssh/ssh_host_ed25519_key.pub' > "$t/role/dbb_hostkey.pub"
        args=(. 10.0.20.15 dbb_hostkey.pub) ;;
    esac
    printf 'set -euo pipefail\ncd "$(dirname "$0")"\nguest/guest.sh offline %q\n(cd role && GUEST_NAME=%q bash ./role.sh %s)\nguest/guest.sh seal %q\nguest/guest.sh online %q\n' \
      "$n" "$n" "${args[*]:-}" "$n" "$n" > "$t/run.sh"
    "$LAB" run farm "$t" run.sh ;;
  *) echo "create|role" >&2; exit 2 ;;
esac
