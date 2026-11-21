# servers/detection — 호스트 쪽 탐지 룰 (서버 안에 설치)

- 결과 기반 감시 P0: `authorized_keys`, `/etc/ld.so.preload`, `/etc/cron.d` auditd 감시 — 11/26
- 미끼 열람 감시: app-01 `~/.aws/credentials`(T6 1차, 60초) — 11/26
- db-backup-01 목적지 탐지: sshd 로그인(미끼 키 지문 A·B, T2·T4), DB 5432 접속(`report_ro`·`sync_svc`, T1·T5) — 11/25
- 디코이 세션 명령 기록(execve, 미끼 계정 auid) — 11/27
- 경보 송신(웹훅 URL은 배포 시 주입) — 11/27

## moa-notify (11/20) — 세 서버 공통 데몬
- `moa-notify/`: Python 표준 라이브러리만, `/opt/moa-notify` + `moa-notify.service`, 설정 `/etc/moa-notify/config.json`(root 0600, 서버마다 켜는 감시 항목만 다름, 저장소에는 `config.example.json`만)
- **서버에 올라가는 코드라 이름·주석에 프로젝트 용어를 쓰지 않는다**(`servers/webapp/`과 같은 규칙)
- 지금 있는 감시: `postgresql` — PG 서버 로그에서 접속 하나를 알림 하나로 묶음(접속 출처, 사용자, DB, 결과). **모든 접속**에 알림, 미끼 계정 이름 목록 없음(11/20 결정). T1/T5 대응은 루트 `detection/`에서
- 다음: sshd(키 지문 A·B, 11/25), auditd(T6 열람, 11/26)
- 테스트: `python3 -m unittest discover -s servers/detection/moa-notify/tests` (서버에 올리지 않음). `tests/fixtures/`는 로컬 VM의 실제 PG16 로그

### 로컬 VM에서 확인한 것 (11/20)
| 접속 | PG 로그에 남은 것 | 알림 |
|---|---|---|
| `report_ro` 틀린 비밀번호 | `password authentication failed for user "report_ro"` + `Role does not exist` | user=report_ro, 비밀번호 인증 실패. libpq 기본(sslmode=prefer)은 **재시도해서 2건** |
| `sync_svc` 비밀번호 없이(`psql -w`) | `connection received` **한 줄뿐** | user 없음(결과 기록 없음) — 사용자명을 잃음 |
| TCP 연결 후 바로 끊기 | `connection received`만 | user 없음 |
| SSL 요청 후 끊기 | `could not accept SSL connection: EOF detected` | user 없음 |
| 로컬 `postgres` | `connection authorized` | 접속 성공 |
- 지연: 로그 시각 → 웹훅 수신 약 1.5~3.5초(TCG VM, 묶음 대기 3초 포함). 60초 기준 안
- logrotate(copytruncate), 데몬 재시작, 데몬이 멈춰 있던 동안의 접속 모두 놓치지 않음
- `base/`의 auditd 규칙은 세 서버 공통 기본 규칙, 여기는 탐지 목적 규칙. 여기 규칙이 디코이에만 깔리면 디코이 전용 흔적이 되므로 진정성 검증 세트에서 측정(변경 A)

## 회귀 테스트
AWS 쪽 룰은 루트 `detection/`에 있다. **두 곳에 걸친 미끼: T6**(호스트 1차 여기 / CloudTrail 2차 `detection/`). 어느 쪽을 고쳐도 시나리오 재실행.
