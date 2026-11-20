# Deceptive-2

시중 디셉션 솔루션의 주요 기능을 AWS 위 가상 회사(모아예약)에 직접 구현하고, 내부 침투 시나리오로 탐지되는지 검증하는 프로젝트. 마감 2026-12-04.
직전 프로젝트: [Cowrie SSH 허니팟 shell/proxy 비교](https://deceptive.ddyoru.cloud/analysis/)

- 목표·원칙: `docs/00-main-goal.md` · 계획·WBS(동결): `docs/plan-wbs.md` · 인프라: `docs/02-infra-design.md`
- 학습 로그(그날 기록): `docs/04-learning-log.md`

## 폴더

**서버에 올라가는 것은 전부 `servers/` 안에 있다.** 그 밖의 폴더는 AWS·로컬에서 실행하는 코드이거나 문서·저장소 설정이다.

| 폴더 | 내용 | 일정 |
|---|---|---|
| `servers/base/` | 세 서버 공통 베이스(auditd 규칙, CloudWatch 에이전트) — 한 벌만(변경 A) | 11/21~22 |
| `servers/hosts/` | 호스트별 역할 구성(app-01, db-backup-01). 공통은 `servers/base/` | 11/21~22, 11/25, 11/27 |
| `servers/webapp/` | 모아예약 웹 앱 + web-01 역할(nginx·systemd) → web-01 `/srv/app` | 11/21 |
| `servers/webapp-history/` | `/srv/app` 서사용 커밋 이력 생성 도구 — **도구는 올리지 않고 결과 디렉터리만** | 11/20(도구), 11/21 배포 |
| `servers/baits/` | 미끼 정의 T1~T7 (템플릿만, 값은 배포 시 주입) | 11/26~27 |
| `servers/detection/` | 호스트 쪽 탐지 룰(auditd 감시, sshd·DB 접속 감시, 경보 스크립트) | 11/26~29 |
| `infra/` | VPC·보안 그룹·인스턴스·CloudTrail (AWS API) | 11/21~22 |
| `validation/` | 진정성 검증 세트 (서버에 대고 실행, 설치 안 함) | 11/23~25 |
| `detection/` | AWS 쪽 탐지 룰(CloudTrail→EventBridge→Lambda), 상관분석, 억제 규칙. T6은 `servers/detection/`과 걸침 | 11/27~12/1 |
| `forensics/` | 출발지 포렌식 스냅샷 (SSM으로 실행) | 11/29 |
| `scenarios/` | 시나리오 1~3, 기준선 정상 작업 | 11/29~12/2 |

### `servers/webapp/` 주의
- 이 폴더는 **가상 회사의 코드**로서 서버에 그대로 올라간다. 이 프로젝트의 용어(미끼·함정·디코이·탐지 등)를 파일·주석에 쓰지 않는다
- 배포는 파일만 복사하고 이 저장소의 `.git`은 올리지 않는다. `/srv/app`의 커밋 이력은 회사 서사에 맞춰 따로 만든다(이 저장소 이력이 올라가면 그 자체가 구별 단서)
- `servers/webapp/moayeyak/receipt.py`의 `build_receipt_pdf()`(예약 확인서 PDF, 의도적 취약점)는 직접 작성한다
- 로컬 확인: `DATABASE_URL=sqlite:///…`로 실행 가능(월간 리포트는 PostgreSQL 전용, 꺼짐 상태)

## 비밀값
- AWS 키·웹훅 URL·미끼 실제 값은 커밋 금지. 미끼 키(`backup-legacy`, T7)는 **실제 IAM 사용자의 실제 키**라 유출되면 봇이 사용 → 기준선·시나리오 오염
- `.gitignore` + gitleaks 커밋 전 훅(`.githooks/pre-commit`, gitleaks가 없으면 커밋 차단). 미끼 템플릿의 `{{ 자리표시자 }}`는 `.gitleaks.toml`에서 허용

### 처음 클론했을 때
```sh
git config core.hooksPath .githooks
# gitleaks: https://github.com/gitleaks/gitleaks/releases 에서 linux_x64 받아 checksums 확인 후 ~/.local/bin
```
