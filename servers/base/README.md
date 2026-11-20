# base — 세 서버 공통 베이스 (변경 A)

web-01·app-01·db-backup-01에 **같은 파일 한 벌**을 배포한다. 호스트별 사본을 만들지 않는다.
어긋난 사본이 곧 "디코이 전용 감시 흔적"(T1518.001 단서)이 되기 때문.

- `install.sh base`: 시간대 Asia/Seoul, auditd·clamav(clamd 없음, freshclam만)·unattended-upgrades·logrotate·cron, audit 규칙
- `install.sh postgresql`: PG가 있는 서버(app-01, db-backup-01)에서 같은 PG 설정 — `postgresql/50-logging.conf`(접속·종료 기록, CIS PostgreSQL Benchmark 권고), `50-listen.conf` + `pg_hba` 내부망(10.0.0.0/16, scram-sha-256)
- 남은 것: CloudWatch 에이전트 설정(계정 필요, 11/21~22)
- 근거: `docs/plan-wbs.md` 3절 기능 1(감시 흔적 동일화 원칙), `docs/02-infra-design.md` 2절
- 디코이 전용으로 허용되는 것: 목적지 탐지에 필요한 DB 리스너뿐(성공 기준). 11/20 진짜 PG로 결정해서 이것도 공통이 됨 → 디코이 전용 0개가 목표

## audit 규칙 (11/20)
| 파일 | 출처 | 이유 |
|---|---|---|
| `10-base-config.rules` | Ubuntu auditd 3.1.2 예제(`/usr/share/doc/auditd/examples/rules/`) | 버퍼·실패 모드 |
| `12-ignore-error.rules` | 같은 예제 | `30-stig`의 `/etc/NetworkManager/` 규칙이 Ubuntu 서버(디렉터리 없음)에서 로드 오류를 내고, **그 뒤 규칙을 전부 건너뜀**(로컬 VM에서 41줄 중 16줄만 로드됨 확인) |
| `30-stig.rules` | 같은 예제 | "보안 가이드를 따라 켜 둔 회사" 모습 |
| `43-module-load.rules` | 같은 예제 | 커널 모듈 적재 |
| `50-user-cmd.rules` | 이 저장소 | 로그인 세션 명령(execve, `auid!=unset`). 디코이 세션 명령 첨부(plan-wbs 77행)를 디코이 전용 규칙 없이 |

- 예제 파일은 서버에 설치된 auditd 패키지에서 바로 복사한다(저장소에 사본 없음 → 패키지 버전과 어긋나지 않음)
- 패키지 기본 `rules.d/audit.rules`는 지운다(이름순으로 맨 뒤에 읽혀 `-D`로 앞 규칙을 지움)
- `99-finalize`(-e 2, 불변)는 쓰지 않음: 미끼·규칙을 SSM으로 교체(변경 C)할 때마다 재부팅이 필요해짐
- **알게 된 것**: `30-stig`는 전부 `auid>=1000` 조건. Ubuntu에는 시스템 계정 `backup`(uid 34)이 원래 있어서 미끼 계정 `backup`의 행동은 STIG 규칙에 안 잡힘 → 명령 기록은 `50-user-cmd`(auid 하한 없음)가 담당
- 확인할 것(11/21, 계정): SSM Session Manager 셸의 auid가 설정되는지(안 되면 관리자 SSM 작업이 `user-cmd`에 안 남음)

## 로컬 확인 (11/20, `infra/local-vm/`)
- Ubuntu 24.04.5 클라우드 이미지 VM에서 `install.sh base` → 규칙 41줄 로드, 서비스 모두 active
