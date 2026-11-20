# infra — AWS 자원

VPC 10.0.0.0/16, public 10.0.1.0/24 / internal 10.0.2.0/24, 보안 그룹, S3 게이트웨이 엔드포인트, 인스턴스 3대, CloudTrail(단일 리전).

- 일정: 11/21(VPC·web-01·app-01), 11/22(db-backup-01·로그 경로·부하 테스트)
- 근거: `docs/02-infra-design.md` 2·3절, `docs/plan-wbs.md` 6절
- `local-vm/`: 로컬 QEMU VM(Ubuntu 24.04 클라우드 이미지)으로 `servers/`를 계정 없이 미리 돌려 보는 도구(11/20). `vm.sh up|ssh|push|down|reset`, 테스트용 웹훅 수신기 `webhook_sink.py`. KVM 권한이 없으면 TCG로 느리게 돈다(`sudo usermod -aG kvm $USER` 후 `wsl --shutdown`, 11/20 적용 — 공통 베이스 설치 4분 32초 → 7초)
- 금지: NAT 게이트웨이. 보안 그룹·미끼는 사설 IP 기준(공인 IP는 재시작 시 바뀜)
