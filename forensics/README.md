# 출발지 포렌식 (Illusive US10382484, 기술 스위치 `forensics`)

벤더 원문(11/24 확인, 일반 설명 FIG. 4~6): 트랩 서버가 "컴퓨터 A에서 미끼 경로로 접속됐다"를 알면 관리 서버가 포렌식 앱을 **실시간으로 A에 보내 실행**하고,
앱은 **트랩에 접속 중인 프로세스 P를 찾아 P가 하는 일을 기록**해 보고한다. 트랩의 **tar-pit 모듈이 들어오는 연결을 일부러 늦춰** 그 시간을 번다.
(청구항 원문은 못 읽음 — 위 내용은 명세서 본문 기준)

## 구조
| 단계 | 어디서 | 하는 일 |
|---|---|---|
| 경보 | 디코이·트랩·팜·회사 서버 moa-notify → 수신기 | 이미 있는 경보(출발 `IP:포트` 또는 감사 pid·ses) |
| 출발지 정하기 | 관리 쪽 `correlate.py` | client IP → 회사 서버(렌더된 맥락). 감사(미끼 열람) 경보는 그 서버 자신. 회사 서버가 아니면 수집 안 함 |
| 보내기 | 환경 프로필 `access.run_py` | 수집기와 인자를 표준입력으로(로컬 SSH·tty 없음, AWS SSM Run Command 11/29). 서버에 파일 안 남김 |
| P 특정 | 출발지 `collect.py` | `/proc/net/tcp`에서 출발 소켓 → inode → 주인 프로세스 = P. 감사 경보는 pid → 끝났으면 부모 → 그것도 없으면 같은 로그인 세션의 살아 있는 셸 |
| 스냅숏 | 〃 | P와 조상(명령줄·exe 해시·cwd·열린 fd·환경 — 앞 홉 `SSH_CONNECTION`), 프로세스 전체, 소켓+주인, 최근 로그인(last·who·auth.log), 최근 2시간 바뀐 파일, 셸 히스토리 |
| P 활동 기록 | 〃 | P의 로그인 세션이 있으면 그 세션의 감사 execve를 세션이 끝날 때까지(최대 `follow_seconds`), 없으면(웹 프로세스에서 뜬 셸 등) P 셸의 자손을 0.5초마다 |
| 사건 | 관리 쪽 `out/forensics/<사건>/` | `alert.json`·`collect.jsonl`·`case.json`(+같은 세션의 다른 경보 `merged.jsonl`), 수신기에 `포렌식` 경보 2번(스냅숏, 추적 끝) |

- P가 이미 끝났으면(빠른 실패): 출발지 감사 기록에서 경보 직전에 목적지 주소·이름을 쓴 로그인 세션 명령을 찾아 P·세션 복원
- 짧은 연결 붙잡기(벤더 tar-pit): 디코이 PG `auth_delay` 3초(공통 설정), 팜 투영 디코이 SYN+ACK 2초(`servers/hosts/farm/tarpit.sh`, 스위치 `forensics`), 디코이 PG·sshd 접속 시작 즉시 경보(moa-notify `immediate`, 스위치 `forensics`)
- 같은 세션(또는 같은 셸)을 이미 추적 중이면 새 수집은 멈추고 그 사건에 붙인다 — 미끼 열람 → 디코이 접속이 한 사건
- 읽기는 `O_NOATIME`(증거 파일의 열람 시각을 안 바꿈). 자기 수집이 낸 감사 경보(수집기 pid)는 무시
- 억제: `config.yml` `audit_skip` = 실행 파일 + auid unset(SSM·CloudWatch 에이전트, ClamAV 03:17 검사 — 로그인 세션에서 돌리면 수집함. 11/30 오탐 분석에서 다시)

## 실행
```
python3 baits/engine.py feature forensics on|off      # 기술 스위치: 상관기 + 세 서버 즉시 경보(immediate) + 팜 연결 지연
python3 forensics/correlate.py watch                    # 수신기 따라가기(로컬: ~/.cache/deceptive2-vm/webhook.jsonl)
python3 forensics/correlate.py once <수신기 줄 번호>      # 경보 하나로 재현
python3 forensics/correlate.py show <사건 ID>
forensics/scenario.sh                                   # 회귀 시나리오(공격자 자리에서 다섯 경로)
```

## 출발지에 남는 것(공격자가 볼 수 있는 것, 11/24 공격자 시점 검사)
- `ps`: root `sudo python3 -`·`python3 -`(인자는 표준입력이라 안 보임 — 처음엔 명령줄에 공격자 자기 pid가 보였음), 세션이 끝날 때까지(최대 300초)
- `last`·`who`: 안 남음(tty 없음). `auth.log`: 관리 계정 로그인 + `sudo ... COMMAND=/usr/bin/python3 -`(adm 그룹·root만 읽음). 감사 로그: 수집기의 `last`·`who` 실행
- AWS(11/29, plan-wbs 3절 기능 4·변경 E): 전달 = SSM Run Command, 결과 보관 = CloudWatch Logs/S3. SSM은 SSH 로그인 대신 에이전트가 문서 스크립트를 `/var/lib/amazon/ssm/` 아래에 쓴다 — 11/29 전환 때 다시 잰다
