# app-01 정상 관리 작업 목록 (기준선 근거)

작성 11/20 · 사용: 11/29 저녁 압축 기준선 스크립트(plan-wbs 5절 "기준선 (시간 압축 방식)")
목적: 기준선에서 돌릴 "정상 작업"을 근거와 함께 미리 고정한다. 기준선이 끝난 뒤 정상 작업을 골라 넣으면, 오탐이 안 나는 작업만 남길 수 있기 때문이다.

## 원칙
- 출처는 plan-wbs 5절 정상 작업 목록이다. 이 중 **app-01에서 실제로 일어나는 것**만 남기고, app-01 역할(운영 PostgreSQL, S3 백업, 02-infra-design 2·4절)에서 생기는 작업을 더했다. 새 작업 범주는 만들지 않는다
- 횟수는 "실제 주기로 48시간 동안 일어나는 횟수"로 정한다(plan-wbs 5절: 벽시계 대신 작업별 실행 횟수). 주기가 하루 미만인 것은 48시간 상당 횟수만큼, 하루 1회 미만인 것은 최소 1회 돌린다
- **예상 오탐**은 지금 설계(02-infra-design 5절 함정, `servers/detection/`)를 기준으로 미리 적는다. 실제 결과는 11/30에 이 표와 비교한다. 예상과 달랐던 것은 학습 로그로 남긴다

## 작업 목록

| # | 작업 | 누가·어떻게 | 실제 주기 → 기준선 횟수 | 건드리는 것 | 예상 오탐 | 근거 |
|---|---|---|---|---|---|---|
| A1 | 관리자 SSM 세션 접속 후 상태 확인(`df`, `free`, `systemctl status`, `journalctl -u postgresql`) | 관리자, SSM Session Manager(`ssm-user`) | 하루 2회 → 4회 | 셸 명령(auditd `user-cmd`) | 없음 | plan-wbs 5절 "관리자 SSM 접속", 02-infra 3절 관리 접속은 SSM |
| A2 | 관리자 SSH 접속(web-01에서 내부망으로) | 관리자, `ssh app-01` | 하루 1회 → 2회 | sshd 로그인 기록, `known_hosts` | 없음(app-01 sshd는 경보 대상 아님) | plan-wbs 5절 "SSH", 02-infra 3절 app-01 22 ← 10.0.0.0/16 |
| A3 | apt 업데이트 | unattended-upgrades(자동, 하루 1회) + 관리자 `apt update && apt upgrade -y`(주 1회) | 자동 2회 + 수동 1회 | `/var/lib/dpkg`, 패키지 스크립트 | P0 `/etc/cron.d` 변경 감시: 패키지가 `/etc/cron.d/*`를 바꾸면(예: sysstat, plocate 업데이트) **오탐 가능** | plan-wbs 5절 "apt 업데이트", 02-infra 2절 공통 베이스 unattended-upgrades |
| A4 | 로그 로테이트 | `logrotate.timer`(하루 1회) | 2회 | `/var/log/*`, PG 로그(postgresql-common 설정) | 없음. 단 `moa-notify`가 PG 로그 잘림(copytruncate)을 놓치는지 확인 | plan-wbs 5절 "로그 로테이트" |
| A5 | **S3 백업 cron**: `pg_dump` → gzip → `aws s3 cp` (IAM 역할 `backup-writer`) | cron, 미끼 파일과 **같은 계정**(02-infra 4절 T6 계정, 계정은 11/27 확정) | 하루 1회 → 2회 | 운영 DB, `~/.aws/config`·**`~/.aws/credentials`**(awscli가 IMDS보다 먼저 읽음), S3 | **T6 호스트 1차(열람 감시) 오탐 예상** — 매 실행마다. 억제 후보: 실행 파일(`aws`) + cron 세션(auid unset) + 시각 | plan-wbs 5절 "S3 백업 cron(실제, IAM 역할)", 02-infra 4절 |
| A6 | 관리자가 백업 결과 확인(`aws s3 ls s3://moayeyak-db-backup-…/`) | 관리자, SSM 세션 | 하루 1회 → 2회 | `~/.aws/credentials`(같은 이유) | **T6 호스트 1차 오탐 예상**. A5와 달리 로그인 세션(auid 있음)이라 "사람이 열었다"와 구별이 어려움 → 자동 차단 판정(변경 D)의 핵심 사례 | 02-infra 4절 "현재" 서사, plan-wbs 5절 오탐 튜닝 |
| A7 | 홈 디렉터리 백업(`tar czf /var/backups/home-….tgz /home`) | root cron | 하루 1회 → 2회 | `/home/*` 전체 내용 읽기 | **T6 오탐 예상**(미끼 파일 내용을 읽음) | plan-wbs 5절 "홈 디렉터리 백업", "예상 오탐원: 미끼 파일 내용을 여는 백업" |
| A8 | `updatedb` | `plocate-updatedb.timer`(설치돼 있으면, 하루 1회) | 2회 | 파일 이름만 읽음 | **오탐 없을 것으로 예상**(이름만 읽음) → 실측 확인 대상 | plan-wbs 5절 "updatedb는 파일 이름만 읽어 안 걸릴 것으로 예상 — 실측으로 확인" |
| A9 | ClamAV 전체 검사 `clamscan -r --infected /home /etc /srv /opt` | 관리자 또는 cron, clamd 없음(11/20 결정) | 주 1회 → 1회 | 파일 내용 전부 | **T6 오탐 예상**. 메모리: t3.micro 1GB에서 시그니처 적재 시 OOM 여부(11/22 부하 테스트) | plan-wbs 5절 "ClamAV 전체 검사", "예상 오탐원" |
| A10 | 내부망 점검 `nmap -sV 10.0.2.0/24`(디코이 포함) | 관리자, app-01에서 실행 | 월 1회 → 1회 | 디코이 22·5432·rsync에 접속 | **디코이 DB 경보 오탐 예상**(경보 조건이 "모든 접속", 11/20 결정) + 디코이 sshd 접속 기록. 사용자명 없는 접속 → 억제 후보 | plan-wbs 5절 "내부망 nmap(디코이 포함)", "디코이 포트를 두드리는 nmap" |
| A11 | 개발자 `grep -r password` (설정 확인) | 개발자, SSH/SSM 세션, `~`·`/etc`·`/srv` | 주 1회 → 1회 | 파일 내용 | **T6 오탐 예상**(`grep`이 credentials 파일을 엶) | plan-wbs 5절 "개발자 `grep -r password`" |
| A12 | 미끼 배포·교체(SSM Run Command / Ansible) | 관리 채널(변경 C) | 배포 1회 + 교체 1회 | `~/.aws/credentials` 쓰기 | **T6 오탐 예상**(배포 채널 자체). 억제 후보: SSM 에이전트 하위 프로세스 | plan-wbs 5절 "Ansible·SSM 배포(미끼 배포 채널 자체가 오탐을 내는지 포함)" |
| A13 | DB 정기 관리 `vacuumdb --analyze`, 느린 쿼리 확인(`psql -c "select … from pg_stat_activity"`) | 관리자 또는 cron(`postgres`) | 주 1회 → 1회 | 운영 DB, PG 로그(`log_connections`로 접속 기록) | 없음(app-01 PG 로그는 경보 대상 아님) | 02-infra 2절 app-01 운영 PostgreSQL, 11/20 결정(PG 로그 설정 app-01 공통) |
| A14 | web-01 앱의 DB 접속(상시) | gunicorn → app-01:5432 | 상시 | PG 로그에 접속 기록 다수 | 없음(같은 이유). **로그 양이 CloudWatch 비용에 미치는 영향**만 기록 | 02-infra 3절 "웹 → 내부 DB 통신은 실제 회사처럼 허용", 11/20 결정 |

## 기준선에서 빼는 것 (이유)
- 시나리오 공격 행동(T1552 등)은 정상 작업이 아니라 넣지 않는다
- app-01에서 일어나지 않는 작업(웹 배포, nginx 재시작)은 web-01 목록에 둔다

## 11/29까지 정할 것
- A5·A6 계정 이름(11/27 T6 배포 때 확정). A10을 실행할 호스트를 app-01로 둔 것은 "내부 업무 서버"라는 역할에서 고른 것이므로, 11/29에 web-01 목록과 겹치지 않는지 확인
- A3 `/etc/cron.d` 오탐 가능성: P0 감시 규칙(11/28)을 만든 뒤 `dpkg -S /etc/cron.d/*`로 패키지가 소유한 파일 목록을 확인
