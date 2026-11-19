# app-01 — 내부 업무 서버 (운영 DB)

- PostgreSQL 16: 운영 DB, 더미 매장·예약 데이터, web-01 → 5432 접속 허용(10.0.0.0/16)
- `pg_dump` → S3 cron: IAM 역할 `backup-writer`(IMDSv2, 키 파일 없음), 버킷 `moayeyak-db-backup-<난수6>`
- awscli
- 일정: 11/21 생성·PostgreSQL, 11/27 S3 백업 cron(실제 동작)
- `[backup-legacy]` 미끼와 전환 흔적은 `baits/`(T6)
- 근거: `docs/02-infra-design.md` 2·4절
