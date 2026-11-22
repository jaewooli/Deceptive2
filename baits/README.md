# baits — 미끼 배포 엔진 (관리 쪽, 서버에 올라가지 않음)

Illusive식 **맥락 기반 원격 배포**(`docs/01-vendor-feature-map.md` 문제 1)를 Ansible 위에 구현. 함정 목록은 손으로 정하지 않고, 미끼 유형별 배치 규칙이 서버 맥락을 읽어 정한다(11/22 사용자 결정).

| 단계 | 하는 일 | 파일 |
|---|---|---|
| ① 원격 배포(에이전트 없음) | Ansible — 로컬은 SSH, AWS는 `community.aws.aws_ssm` 연결(같은 코드) | `playbooks/` |
| ② 맥락 수집 | 셸 계정·나가는 ssh 흔적·히스토리 도구·서비스 환경 파일 **변수 이름과 값의 모양**·이름 해석 방식·awscli/프로필 이름·파일 시각. **비밀값은 읽지 않음** | `collect_context.py` |
| ② 규칙으로 선택·맞춤 | 유형별 `match`(맥락이 없으면 두지 않음) → `new_ident` → `ops`(그 파일의 형식·변수 이름·키 이름 규칙·시각을 따름) | `bait_types.py` |
| ③ 고유 ID 레지스트리 | 미끼 → 기계·위치·ID, 교체된 옛 ID 포함. 로컬 `out/baits/registry.json`(커밋 안 함), AWS는 비공개 S3 | `engine.py` |
| ④ 드리프트 | `verify`: 사라지거나 바뀐 미끼 = **경보 + 복구** | `engine.py` |
| ⑤ 교체·회수 | `rotate`(명령 + 주 1회, 옛 ID는 retired로 계속 감시), `recall` | `engine.py` |

- 서버에서 도는 것은 `collect_context.py`·`apply_ops.py` 두 개뿐이고 Ansible `script`로 실행 뒤 남지 않는다. 미끼 내용은 root 0600 임시 파일로 넘긴다(명령 인자로 넘기면 auditd execve 기록에 남음 — 11/22 실측)
- 관리 표시(`# BEGIN ANSIBLE MANAGED BLOCK` 등)를 남기지 않고, 고친 파일의 시각은 원래 값으로 되돌린다
- 디코이 쪽 작업(SSH 미끼 공개키 → db-backup-01 `backup`의 `authorized_keys`)도 같은 채널로
- 미끼 유형(11/22)
  | 유형 | 맥락 조건 | 무엇 |
  |---|---|---|
  | `env_db_url`(T1형) | 앱 환경 파일이 PostgreSQL을 쓰고 비어 있는 `*_DB_URL`(꺼진 기능)이 있음 | 그 기능의 읽기 전용 계정으로 디코이 DB 주소. 다른 서버를 `/etc/hosts`로 찾는 서버면 디코이 이름도 |
  | `ssh_config`(T2형) | 나가는 ssh를 쓰는 계정(known_hosts·개인키·config·히스토리) | Host 블록 + 키 + **known_hosts**(없으면 첫 접속 질문이 단서) + 디코이 `backup` authorized_keys |
  | `history`(T3형) | T2 계정에 히스토리 20줄 이상 | 세션 경계(`exit` 다음)에 한 세션 덩어리, 앞쪽 60% 지점(끝이면 "최근에 썼다"가 됨) |
  | `aws_profile`(T6형) | 그 계정의 cron(또는 cron이 부르는 스크립트)이 aws를 씀 | `[backup-legacy]` 장기 키(로컬은 형식만, AWS는 IAM 실제 키) |
  | `agent_session`(T4형) | 히스토리 있는 사람 계정 + 나가는 ssh + tmux·ssh-agent 있음 | **잊힌 tmux 세션의 ssh-agent에만** 키(디스크엔 없음). 재부팅으로 사라지면 경보 없이 다시 엶 |
  | `sync_service`(T5형) | 앱 환경 파일에 꺼진 기능 플래그(`*_ENABLED`) + 그 기능의 DB 주소 | 그 기능의 동기화 서비스가 대기만 하며 살아 있음, 유닛 `Environment=`에 디코이 DB 계정(디코이로 가는 정상 트래픽 없음) |
  | `decoy_port`(11/22, Illusive US10404747) | 운영 서버(EDH)의 역할(postgres → Redis 6379, nginx → 내부 관리 8080) + 그 포트를 안 씀 | EDH의 안 쓰는 포트 → **터널로 farm 트랩**(EDH 주소를 자기 NIC에 가진 컨테이너, hostname = EDH, 진짜 서비스). 단계: EDH 키 → farm 트랩 → EDH 터널 → 공통 데몬 `ports` 설정 |
  | `cache_hint`(11/22) | 앱이 DB로 쓰는 서버에 **활성** Redis 디코이 포트가 있음(특허: 활성 디코이 포트만 가리킴) | 보류된 세션 캐시 설정이 주석으로 남은 모양(앱 코드에 없는 변수라 살아 있는 설정이면 git grep에서 어색) |
- 레지스트리 상태: pending(서버 손대기 전 기록) → active / failed(회수로 정리) / retired(교체됨, 계속 감시) / recalled / **released**(디코이 포트를 실제 프로그램이 쓰기 시작해 데몬이 양보 — verify가 상태 파일을 읽어 표시, 포트가 비면 다음 plan이 다시 제안. 데몬이 스스로 다시 잡지 않는 이유: 실제 서비스 재시작 틈에 가로채면 운영 트래픽을 트랩으로 넘김) / duplicate
- 작업 순서: 출발 서버 먼저, 성공해야 디코이 쪽. verify는 디코이 authorized_keys의 모르는 일반 키도 경보(자동 삭제 안 함)
- 남은 것: 옛 ID(retired 키) 사용 탐지엔 sshd `LogLevel VERBOSE`가 세 서버 공통으로 필요(CIS 권고) — 탐지 단계에서

```sh
python3 baits/engine.py collect && python3 baits/engine.py plan    # 무엇을 어디에 둘지
python3 baits/engine.py apply | verify | rotate --all | recall --all | list
```
관리 쪽 준비: `python3 -m venv ~/.cache/deceptive2-ctl && ~/.cache/deceptive2-ctl/bin/pip install ansible-core==2.17.7` + `ansible-galaxy collection install -p ~/.cache/deceptive2-ctl/collections ansible.posix:1.6.2 community.aws:8.0.0 amazon.aws:8.2.1`

## 11/22 첫 실행에서 알게 된 것
- **맥락 기반 배치는 서버가 진짜로 쓰인 서버일 때만 성립한다.** 로컬 web-01 `deploy`는 나가는 ssh 흔적이 없고 앱 DB가 SQLite(로컬 편의) → 규칙이 아무것도 두지 않음. 벤더는 고객의 실제 단말에서 맥락을 얻지만, 랩에선 정상 서버의 사용 흔적부터 만들어야 한다
- 규칙 오판 하나: `~/.ssh`가 있다고 "ssh를 쓴다"로 봤더니 cloud-init `authorized_keys`만 있는 `ubuntu`에 SSH 미끼를 두려 함 → 나가는 흔적(known_hosts·개인키·ssh config·히스토리)만 세게 고침
- T4·T5에서 또: ① 미끼가 자리를 차지하면 맥락이 바뀌어(빈 값 → 채워짐) 규칙이 "맥락 사라짐"으로 오판 → 규칙이 자기 미끼 자리를 같은 자리로 인식 ② 적용이 중간에 실패하면 서버엔 일부 적용, 레지스트리엔 없음(고아) → 먼저 pending으로 기록 ③ 출발 서버가 실패해도 디코이 쪽 키 추가는 같은 플레이북에서 돌아 고아 키가 쌓임 → 두 단계 + 목적지 감사
