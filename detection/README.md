# detection — 탐지 룰 · 억제 규칙 · 경보 · 상관분석

- 결과 기반 감시 P0(`authorized_keys`, `/etc/ld.so.preload`, `/etc/cron.d`) — 11/28
- 디코이 로그인·미끼 DB 계정 접속 경보, 웹훅, 침투 체인 상관분석, 세션 명령 첨부 — 11/29
- CloudTrail → EventBridge → Lambda → 웹훅(AWS 키 2차 탐지) — 11/27
- 억제 규칙 — 12/1 (기준선 오탐 원인 분석 후)
- 근거: `docs/plan-wbs.md` 3절 기능 2·3·4, 5절 성공 기준
- 웹훅 URL은 커밋 금지(배포 시 주입). 수정 시 시나리오 재실행(회귀 테스트)
