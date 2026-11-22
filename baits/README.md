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
- 미끼 유형(11/22): `env_db_url`(T1형) · `ssh_config`(T2형) · `history`(T3형, T2의 길잡이) · `aws_profile`(T6형). 프로세스형(T4 ssh-agent·T5 환경변수)은 다음

```sh
python3 baits/engine.py collect && python3 baits/engine.py plan    # 무엇을 어디에 둘지
python3 baits/engine.py apply | verify | rotate --all | recall --all | list
```
관리 쪽 준비: `python3 -m venv ~/.cache/deceptive2-ctl && ~/.cache/deceptive2-ctl/bin/pip install ansible-core==2.17.7` + `ansible-galaxy collection install -p ~/.cache/deceptive2-ctl/collections ansible.posix:1.6.2 community.aws:8.0.0 amazon.aws:8.2.1`

## 11/22 첫 실행에서 알게 된 것
- **맥락 기반 배치는 서버가 진짜로 쓰인 서버일 때만 성립한다.** 로컬 web-01 `deploy`는 나가는 ssh 흔적이 없고 앱 DB가 SQLite(로컬 편의) → 규칙이 아무것도 두지 않음. 벤더는 고객의 실제 단말에서 맥락을 얻지만, 랩에선 정상 서버의 사용 흔적부터 만들어야 한다
- 규칙 오판 하나: `~/.ssh`가 있다고 "ssh를 쓴다"로 봤더니 cloud-init `authorized_keys`만 있는 `ubuntu`에 SSH 미끼를 두려 함 → 나가는 흔적(known_hosts·개인키·ssh config·히스토리)만 세게 고침
