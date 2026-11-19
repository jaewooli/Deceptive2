# servers/detection — 호스트 쪽 탐지 룰 (서버 안에 설치)

- 결과 기반 감시 P0: `authorized_keys`, `/etc/ld.so.preload`, `/etc/cron.d` auditd 감시 — 11/28
- 미끼 열람 감시: app-01 `~/.aws/credentials`(T6 1차, 60초) — 11/27
- db-backup-01 목적지 탐지: sshd 로그인(미끼 키 지문 A·B, T2·T4), DB 5432 접속(`report_ro`·`sync_svc`, T1·T5) — 11/26
- 디코이 세션 명령 기록(execve, 미끼 계정 auid) — 11/29
- 경보 송신 스크립트(웹훅 URL은 배포 시 주입) — 11/29
- `base/`의 auditd 규칙은 세 서버 공통 기본 규칙, 여기는 탐지 목적 규칙. 여기 규칙이 디코이에만 깔리면 디코이 전용 흔적이 되므로 진정성 검증 세트에서 측정(변경 A)

## 회귀 테스트
AWS 쪽 룰은 루트 `detection/`에 있다. **두 곳에 걸친 미끼: T6**(호스트 1차 여기 / CloudTrail 2차 `detection/`). 어느 쪽을 고쳐도 시나리오 재실행.
