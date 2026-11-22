# webapp-history — `/srv/app` 서사용 커밋 이력 (서버에 올리지 않음)

`servers/webapp`을 회사 서사에 맞는 git 이력과 함께 디렉터리로 만든다. **배포하는 것은 결과 디렉터리(.git 포함)뿐**이고, 이 도구와 이 저장소의 `.git`은 올리지 않는다(README "servers/webapp 주의").

```sh
python3 servers/webapp-history/build_history.py --out /tmp/srv-app
```

- 시간표: 개발 시작 2024-03 → 서버 구축·운영 시작 2024-06 → S3 전환 2025-09 → 서버 재구축 2026-11(`docs/02-infra-design.md` 4절). 2024-06 전 커밋은 출시 전 개발. 재구축 때 `/srv/app`은 `rsync -a`로 옮겨 파일 시각 유지. 커밋 15개, 작성자 가상 2명(`@moayeyak.example`)
- 2024-07 월간 리포트가 백업 서버 DB 사본(`report_ro@db-backup-01`)을 읽도록 추가 → 2025-09 S3 전환으로 끔. T1(`/srv/app/.env`의 남은 `REPORT_DB_URL`, 11/26)의 맥락. T1 실제 값의 계정·DB 이름을 이 이력과 맞출 것
- 의존성: 커밋 날짜 이전에 PyPI에 나온 최신 정식 버전(`pypi-release-dates.json`, 2026-11-20 조회 스냅숏). 현재 고정 버전 중 SQLAlchemy 2.1.9가 2026-11-16 배포라 마지막 의존성 커밋은 2026-11-18. 고정 버전을 바꾸면 스냅숏 갱신 필요(도구가 날짜를 검사해 실패함)
- **`receipt.py`는 실행 시점 내용 그대로** 2024-05-13 커밋에 들어간다. `build_receipt_pdf()`를 작성한 뒤 다시 실행하고, 새 패키지를 쓰면 `requirements.txt`·스냅숏에 추가
- `servers/webapp` 코드를 고치면 이 도구의 중간 단계 변환이 깨질 수 있다 → 실패 메시지대로 단계를 고친다. 마지막 트리가 `servers/webapp`과 다르면 도구가 실패한다

## 확인한 것 (11/20)
- 마지막 커밋 트리 = `servers/webapp` (도구가 검사)
- 15개 커밋마다 앱 생성·`/`·`/stores`·`/admin/login`·예약 폼 응답 확인(현재 의존성 venv, sqlite)
- reflog 시각 = 커밋 시각(`GIT_COMMITTER_DATE`), 작업 트리 파일 시각 = 그 파일을 마지막으로 바꾼 커밋 시각

## 남는 단서 (한계로 기록)
- `.git` 내부 파일(objects, index, COMMIT_EDITMSG)의 시각은 만든 날. 서버에 복사할 때 유지되지 않으면 배포 날짜가 됨
- 작성자 메일 도메인 `.example`은 예약 도메인이라 가상임을 알 수 있음(11/20 결정의 대가)
