# db-backup-01 — 옛 DB 백업 서버 (디코이, 실제 OS)

- 진짜 OpenSSH, IP별 sshd 인스턴스(보조 사설 IP 최대 3개, 포트·배너 분리 — 상한 3시간)
- rsync 수신 설정(중단된 상태), `backup` 계정, `/backup/dumps` 옛 덤프(S3 전환 시점까지)
- 복원 검증용 DB 5432 — **미결정**: Python 더미 리스너 vs 진짜 PostgreSQL + `log_connections` (11/22 전 결정)
- 사용 흔적은 S3 전환 시점까지만 쌓이고 그 뒤 멈춘 모습
- 일정: 11/22 생성, 11/25 사용 흔적 보완·다중 주소
- 근거: `docs/02-infra-design.md` 2·4절, `docs/plan-wbs.md` 3절 기능 1
