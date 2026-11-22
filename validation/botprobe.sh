#!/usr/bin/env bash
# 자동 층(봇) 검사 S1~S4 — 직전 Cowrie 프로젝트에서 봇이 실제로 돌린 확인 명령을 그대로 재현한다
# (https://deceptive.ddyoru.cloud/analysis/ : 셸 동작 5종, 없는 명령 오류, 스크립트 실행, last, CPU·GPU·아키텍처·uptime)
# 봇처럼 바깥에서 SSH로 일반 계정 로그인 → 셸에 명령을 흘려 넣는다. root 권한 없이 보이는 것만 본다
#   validation/botprobe.sh <ssh 명령...>     예) validation/botprobe.sh infra/local-vm/vm.sh ssh
# 남는 흔적: SSH 로그인 1회, /tmp에 스크립트 파일 1개(바로 지움) — 봇도 똑같이 남긴다
set -uo pipefail
"$@" sh -s <<'EOF'
echo "### S1"
echo "token=k7Qx2"
echo "arith=$((593*540+44))"
echo "pid=$$"
set -- a b c; echo "setargs=$#:$2"
f() { echo "fn=$1"; }; f 7
echo "### S2"
nonexist_cmd_zq 2>&1 | sed 's/^/err=/'
t=/tmp/.s$$; printf 'echo script=ok\n' > "$t" && sh "$t"; rm -f "$t"
echo "### S3"
echo "nproc=$(nproc)"
echo "cpu=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//')"
echo "arch=$(uname -m)"
echo "uname=$(uname -srvmo)"
echo "gpu=$( (lspci 2>/dev/null | grep -icE 'vga|3d|nvidia') || echo 0)"
echo "mem_mib=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)"
echo "busybox=$(command -v busybox || echo none)"
echo "### S4"
echo "uptime_s=$(cut -d. -f1 /proc/uptime)"
echo "last_readable=$(last -n 1 >/dev/null 2>&1 && echo yes || echo no)"
echo "last_users=$(last -w 2>/dev/null | awk '$1!="reboot" && $1!="wtmp" && NF {print $1}' | sort -u | tr '\n' ' ')"
echo "w_users=$(who | awk '{print $1}' | sort -u | tr '\n' ' ')"
EOF
