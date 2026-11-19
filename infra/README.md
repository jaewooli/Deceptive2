# infra — AWS 자원

VPC 10.0.0.0/16, public 10.0.1.0/24 / internal 10.0.2.0/24, 보안 그룹, S3 게이트웨이 엔드포인트, 인스턴스 3대, CloudTrail(단일 리전).

- 일정: 11/21(VPC·web-01·app-01), 11/22(db-backup-01·로그 경로·부하 테스트)
- 근거: `docs/02-infra-design.md` 2·3절, `docs/plan-wbs.md` 6절
- 금지: NAT 게이트웨이. 보안 그룹·미끼는 사설 IP 기준(공인 IP는 재시작 시 바뀜)
