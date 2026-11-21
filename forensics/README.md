# forensics — 출발지 포렌식 스냅샷 (변경 E)

경보가 나면 상관분석이 찾은 출발 내부 IP의 인스턴스에 SSM Run Command로 수집: 프로세스 목록, 네트워크 연결, 최근 로그인, 최근 변경 파일, 셸 히스토리 → CloudWatch Logs/S3.

- 일정: 11/27 스크립트(로컬, SSH로 실행, 상한 4시간 — 넘으면 프로세스 목록 + 네트워크 연결만), 11/29 SSM Run Command 전환
- 근거: `docs/plan-wbs.md` 3절 기능 4
