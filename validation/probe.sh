#!/usr/bin/env bash
# 바깥에서 보는 서비스 응답(E1 SSH, E2 PG) — 공격자 시점. 측정하는 쪽(같은 내부망의 다른 서버, 로컬은 WSL)에서 실행
#   validation/probe.sh <주소> <ssh포트> <pg포트>
# SSH는 인증 방법 none까지만(로그인 시도 없음). PG는 없는 계정 1회 → 디코이에서는 경보가 정상
set -uo pipefail
H=${1:?주소} SP=${2:-22} PP=${3:-5432}
echo "### E1"
ssh -vvv -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -o PreferredAuthentications=none -o ConnectTimeout=5 -p "$SP" nobody_check@"$H" true 2>&1 |
  awk '/Remote protocol version|Authentications that can continue/ {print; next}
       /peer server KEXINIT proposal/ {p=1; next} /first_kex_follows/ {p=0}
       p && /(KEX algorithms|host key algorithms|ciphers stoc|MACs stoc|compression stoc):/' |
  sed -E 's/^debug[0-9]: //; s/, remote software version/ software/'
echo "### E2"
python3 -I "$(dirname "$0")/pgprobe.py" "$H" "$PP" 2>&1
