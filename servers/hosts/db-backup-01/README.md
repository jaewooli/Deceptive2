# db-backup-01 — 옛 DB 백업 서버 (디코이, 실제 OS)

- 진짜 OpenSSH(주소 1개 — 11/22 다중 주소는 투영(`../sensor`·`../farm`)으로 대체)
- rsync 수신 설정(중단된 상태), `backup` 계정, `/backup/dumps` 옛 덤프(S3 전환 시점까지)
- 복원 검증용 DB 5432 — **진짜 PostgreSQL 16**(11/20 결정). 미끼 계정(`report_ro`·`sync_svc`)은 만들지 않아 로그인 실패. 접속 기록은 공통 PG 설정(`../../base/postgresql/`, app-01과 같은 파일)으로 남기고 `moa-notify`가 읽음(`../../detection/moa-notify/`)
- 설치 순서(11/22): 공통 `base/install.sh base` → `install.sh`(PostgreSQL) → `base/install.sh postgresql` → `carryover/make_carryover.py --app-ip <app-01 IP>`(옮겨 온 데이터, 한 번만, 실행 뒤 디렉터리 삭제) → `base/install.sh hostkeys "2024-06-12 14:21:37"`
- **배포 파일은 서버에 남기지 않는다**(임시 경로에 풀고 실행 뒤 삭제 — 11/22 로컬 VM에 `~/servers`가 남아 README의 프로젝트 용어가 걸림)
- 사용 흔적은 S3 전환 시점까지만 쌓이고 그 뒤 멈춘 모습
- 일정: 11/24 사용 흔적 보완·다중 주소(로컬 VM), 11/28 AWS 생성
- 근거: `docs/02-infra-design.md` 2·4절, `docs/plan-wbs.md` 3절 기능 1
