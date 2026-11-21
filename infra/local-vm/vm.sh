#!/usr/bin/env bash
# 로컬 Ubuntu 24.04 VM (QEMU) — 계정 없이 servers/ 설정을 미리 돌려 보는 용도
#   infra/local-vm/vm.sh up      # 이미지 받기(처음 1회) → VM 시작 → SSH 가능할 때까지 대기
#   infra/local-vm/vm.sh ssh [명령]
#   infra/local-vm/vm.sh push    # 저장소 servers/ 를 VM ~/servers 로 복사
#   infra/local-vm/vm.sh down    # VM 종료(디스크 유지)
#   infra/local-vm/vm.sh reset   # VM 종료 + 디스크 삭제(깨끗한 이미지에서 다시)
# KVM: 계정이 kvm 그룹에 없으면 TCG(소프트웨어 에뮬레이션)로 돌아 느리다.
#   한 번만: sudo usermod -aG kvm "$USER"  후 Windows에서 wsl --shutdown
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
DIR=${VM_DIR:-$HOME/.cache/deceptive2-vm}
NAME=${VM_NAME:-db-backup-01}
IMG_URL=https://cloud-images.ubuntu.com/noble/current
BASE=$DIR/noble-server-cloudimg-amd64.img
DISK=$DIR/$NAME.qcow2
SEED=$DIR/seed-$NAME
KEY=$DIR/id_ed25519
SSH_PORT=${VM_SSH_PORT:-2222}
PG_PORT=${VM_PG_PORT:-15432}
SEED_PORT=${VM_SEED_PORT:-8099}
MEM=${VM_MEM:-2048}   # t3.small
CPUS=${VM_CPUS:-2}

ssh_opts=(-i "$KEY" -p "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5)

fetch_image() {
  mkdir -p "$DIR"
  [ -f "$BASE" ] && return
  (cd "$DIR" && curl -fsSLO "$IMG_URL/SHA256SUMS" && curl -fSLO "$IMG_URL/$(basename "$BASE")" \
     && grep " \*\?$(basename "$BASE")$" SHA256SUMS | sha256sum -c -)
}

make_seed() {
  [ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N "" -f "$KEY" -C local-vm
  mkdir -p "$SEED"
  cat > "$SEED/meta-data" <<EOF
instance-id: $NAME-$(date +%s)
local-hostname: $NAME
EOF
  cat > "$SEED/user-data" <<EOF
#cloud-config
timezone: Asia/Seoul
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - $(cat "$KEY.pub")
EOF
  : > "$SEED/vendor-data"
}

accel() {
  if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then echo "-accel kvm -cpu host"; else echo "-accel tcg -cpu max"; fi
}

up() {
  fetch_image
  if [ -f "$DIR/$NAME.pid" ] && kill -0 "$(cat "$DIR/$NAME.pid")" 2>/dev/null; then echo "이미 실행 중"; wait_ssh; return; fi
  [ -f "$DISK" ] || qemu-img create -q -f qcow2 -F qcow2 -b "$BASE" "$DISK" 20G
  make_seed
  # cloud-init NoCloud 시드를 HTTP로 제공(게스트에서 10.0.2.2 = 호스트 127.0.0.1)
  python3 -m http.server "$SEED_PORT" --bind 127.0.0.1 --directory "$SEED" >"$DIR/seed-http-$NAME.log" 2>&1 &
  echo $! > "$DIR/seed-http-$NAME.pid"
  # shellcheck disable=SC2046
  qemu-system-x86_64 $(accel) -m "$MEM" -smp "$CPUS" -machine q35 \
    -drive file="$DISK",if=virtio,format=qcow2 \
    -netdev user,id=n0,hostfwd=tcp:127.0.0.1:"$SSH_PORT"-:22,hostfwd=tcp:127.0.0.1:"$PG_PORT"-:5432 \
    -device virtio-net-pci,netdev=n0 \
    -smbios type=1,serial="ds=nocloud;s=http://10.0.2.2:$SEED_PORT/" \
    -display none -serial file:"$DIR/$NAME-console.log" \
    -daemonize -pidfile "$DIR/$NAME.pid"
  echo "VM 시작 ($(accel | cut -d' ' -f2)), 콘솔 로그: $DIR/$NAME-console.log"
  wait_ssh
}

wait_ssh() {
  for _ in $(seq 1 180); do
    if ssh "${ssh_opts[@]}" ubuntu@127.0.0.1 'cloud-init status --wait >/dev/null 2>&1; true' 2>/dev/null; then
      echo "SSH 준비됨: ssh -i $KEY -p $SSH_PORT ubuntu@127.0.0.1"
      stop_seed; return
    fi
    sleep 5
  done
  echo "SSH 대기 시간 초과. 콘솔 로그 확인" >&2; exit 1
}

stop_seed() { [ -f "$DIR/seed-http-$NAME.pid" ] && kill "$(cat "$DIR/seed-http-$NAME.pid")" 2>/dev/null; rm -f "$DIR/seed-http-$NAME.pid"; }

down() {
  local pid=""
  [ -f "$DIR/$NAME.pid" ] && pid=$(cat "$DIR/$NAME.pid")
  ssh "${ssh_opts[@]}" ubuntu@127.0.0.1 'sudo poweroff' 2>/dev/null || true
  # TCG에서는 종료가 느리다: 최대 60초 기다린 뒤 강제 종료
  for _ in $(seq 1 60); do { [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; } && break; sleep 1; done
  [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  rm -f "$DIR/$NAME.pid"; stop_seed
}

case "${1:-}" in
  up) up ;;
  ssh) shift; exec ssh "${ssh_opts[@]}" ubuntu@127.0.0.1 "$@" ;;
  push) tar -C "$REPO" -czf - servers | ssh "${ssh_opts[@]}" ubuntu@127.0.0.1 'rm -rf ~/servers && tar -xzf -' ;;
  down) down ;;
  reset) down; rm -f "$DISK"; rm -rf "$SEED" ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
