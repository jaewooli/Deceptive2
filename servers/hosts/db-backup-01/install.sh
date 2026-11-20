#!/usr/bin/env bash
# db-backup-01 역할 설치. root로, 공통 설정(../../base/install.sh) 다음에 실행.
# 11/20: PostgreSQL만. sshd(IP별)·rsync·backup 계정·옛 덤프는 11/22·11/25에 추가
set -euo pipefail
cd "$(dirname "$0")"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -q postgresql-16
../../base/install.sh postgresql
