#!/usr/bin/env bash
# web 서버 패키지 (Ubuntu 24.04). root로 실행, 여러 번 실행해도 됨
#   sudo bash deploy/install.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -q
# python3-venv: 우분투 기본 python3에는 venv(ensurepip)가 빠져 있음
apt-get install -y -q nginx python3-venv
# 예약 확인서 PDF (receipt.py가 /usr/bin/weasyprint 호출, 템플릿 글꼴 NanumGothic)
apt-get install -y -q weasyprint fonts-nanum
