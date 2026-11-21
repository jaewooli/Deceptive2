# detection — AWS 쪽 탐지 룰 · 경보 처리 (서버 밖)

호스트에 설치되는 룰은 `servers/detection/`에 있다.

- CloudTrail(단일 리전) → EventBridge → Lambda → 웹훅: `backup-legacy` 키(T6 2차), 실험 키(T7) — 11/28. 읽기 전용 호출 전달 여부 먼저 확인, 안 되면 CloudWatch Logs 지표 필터
- 침투 체인 상관분석(미끼 고유 ID → 미끼 위치 호스트 → 출발 내부 IP → 계정 → 이후 행동) — 11/27
- 억제 규칙 — 12/1 (기준선 오탐 원인 분석 후)
- 미끼 ID 대응(서버 밖에서만): 디코이 PG 알림의 `user` — `report_ro` → T1, `sync_svc` → T5. 서버의 `moa-notify` 설정에는 이 목록을 두지 않는다(11/20 결정)
- 근거: `docs/plan-wbs.md` 3절 기능 2·4, 5절 성공 기준
- 웹훅 URL은 커밋 금지(배포 시 주입)

## 회귀 테스트
**두 곳에 걸친 미끼: T6**(CloudTrail 2차 여기 / 호스트 1차 `servers/detection/`). 어느 쪽을 고쳐도 시나리오 재실행.
