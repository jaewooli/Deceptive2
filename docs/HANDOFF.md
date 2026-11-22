# 세션 인수인계 (2026-11-22 → 다음 세션)

**새 세션은 이 문서부터 읽는다.** 그다음 `CLAUDE.md`, `docs/plan-wbs.md` 8절 진행 기록(11/22 항목들), `docs/04-learning-log.md` 11/22 항목들.
11/22 세션 하나(커밋 `1ee44fd`~`6f25aeb`, 약 20개)가 원래 일정 4~5일분 + 계획 변경을 처리했다. 아래는 그 세션의 모든 맥락이다.

## 0. 잊으면 안 되는 기준 (사용자가 여러 번 강조)
- **이 프로젝트의 중심 = 시중 디셉션 기술을 벤더 메커니즘대로 직접 구현하고, 벤더가 왜 그렇게 설계했는지 깨닫고, 공격자 앞에서 먹히는지 검증.** 도구·인프라 개선은 수단일 뿐
- **임의로 간략화하지 않는다.** 계획 문서에 축소가 적혀 있어도(예: 11/19 "투영 → IP별 포트·배너") 벤더 원문(특허·데이터시트)과 대조해 차이를 먼저 알리고 묻는다. 사용자가 이 문제로 크게 화냄
- **비용은 판단 근거로 쓰지 않는다**(사용자: "비용은 따지지 말라"). NAT 금지·안 쓰는 자원 정리·Budgets는 CLAUDE.md 규칙 그대로
- 결정은 만들기 전에 근거를 붙여 한 번에 묻는다. 문서·저장소로 확인 가능한 것은 확인 먼저
- 기능마다: ① 벤더 원문 확인 ② **공격자 시점 검사를 먼저 정함** ③ 구현 ④ 학습 로그(벤더 설계 → 해보니 → 막힘 → 깨달음) ⑤ 시간 상한
- 마감 2026-12-04, 늘어지지 않는다(피드백). 남은 일은 원래 일정 작업과 묶는다
- 메모리: `~/.claude/projects/.../memory/` — core-vendor-implementation, no-silent-simplification, ask-decisions-with-evidence, judge-by-project-goal

## 1. 11/22에 한 일 (요약 — 상세는 plan-wbs 8절)
| 영역 | 결과 | 커밋 |
|---|---|---|
| 문서 정리 | AWS 전환 때 남은 "비교 기준 = 개인 서버(OCI)" 삭제 → 비교 = app-01 + 서사 시간표·배포판 기본값 | 1ee44fd |
| 진정성 검증 세트 | `validation/collect.sh`·`probe.sh`·`pgprobe.py`·`botprobe.sh`·`probe_addrs.sh`·`compare.py`. **자동 층(봇, 직전 Cowrie 관측 근거 S1~S4·E)·사람 층(시멘틱 A·B·C·D·F)** 44개 항목(B7 컨테이너 정체 추가) | 0acde84~ad528ec |
| 서사 수정(사용자 결정) | 운영 시작 2024-03 → **2024-06**(구축 2024-06-12, Ubuntu 24.04 출시 충돌), **2026-11 서버 일괄 재구축**(데이터·홈·호스트 키는 rsync -a로 이전, 옛 백업 서버도 같이 옮김) — 한계: 오래 운영된 정상 서버를 기간 안에 못 만듦, IMDS pendingTime은 못 바꿈 | a5ac689 |
| 디코이 옮겨 온 데이터 | `servers/hosts/db-backup-01/carryover/make_carryover.py`: backup 계정·히스토리·덤프 45개(최근 30 + 매월 첫, PG 버전·`\restrict`를 Launchpad 배포 이력대로)·rrsync 키·복원 DB·주석 cron. `--dump-at`(stg-01용), `--live`(app-01 운영 DB, 2025-10-21 updated_at 마이그레이션 재현, 오늘 지금까지) | a5ac689·65718b8 |
| 넓이: 다중 주소 → **진짜 투영**(사용자 결정) | sensor(투영 주소만, 서비스 없음) → WireGuard → farm(systemd-nspawn) → **stg-01**(옛 스테이징, 2025-05-12 커밋, 덤프 복원, deploy 히스토리). db-backup-01은 IP 1개 | c31cea6 |
| 축소 감사 | 벤더 대비 축소·누락 10개 + NAT → "싹 다 고친다", 1번부터 | — |
| **1번 맥락 기반 미끼 배포**(Illusive US10382483) | `baits/` 엔진: collect(값 안 읽음) → 규칙(유형 8개) → apply(표시 없음·시각 보존)·verify(드리프트=경보+복구)·rotate(옛 ID retired)·recall·refresh. 레지스트리 `out/baits/registry.json`. 정상 서버 사용 흔적(web-01 deploy·git 이력·app-01 PG 실제 연결, app-01 postgres S3 백업). T4 잊힌 tmux ssh-agent, T5 대기 중 report-sync | 45c81fa~f866548 |
| **2번 트랩 서버 중계**(Illusive US10404747) | EDH(web-01·app-01)의 안 쓰는 포트(역할 규칙: DB→Redis 6379, 웹→관리 8080) → 터널 → farm 트랩 컨테이너(EDH 주소·hostname, 공식 클라우드 이미지, 진짜 redis/nginx). moa-notify `ports` 감시(경보·양보), released 루프, `cache_hint`(활성 디코이 포트만 가리킴) | ec60d90·ec3b0dd |
| **3번 연결 테이블 미끼**(**Attivo** US10375110 — 벤더 문서의 Illusive 귀속 정정) | report-sync가 db-backup-01:5432에 핸드셰이크만 한 연결 → 공격자 `ss -tan`·`ip neigh`에 디코이. 디코이 moa-notify **페이로드 관문**(TPROXY): 페이로드 없으면 조용히, 첫 바이트 = 경보 + PG로(진짜 출발지) | aad679b |
| 로컬 랩 가속 + 견고성 | `infra/local-vm/lab.sh`, balloon, 메모리 재할당(5대 동시), `apt_cache.py`. 재부팅·networkd 재시작 시험에서 운영 서버 먹통 버그 발견·수정(아래 3절) | 6f25aeb |

## 2. 지금 구조 (로컬 랩)
```
infra/local-vm/lab.sh up all        # 5대: app-01(lt-app) web-01 db-backup-01(lt-decoy) farm(lt-farm) sensor(lt-sensor)
infra/local-vm/lab.sh ssh <역할> '명령'   /  run <역할> <디렉터리> <스크립트> 인자  /  status  /  mem
```
| 역할 | 공유 LAN(10.0.20.0/24, QEMU 멀티캐스트) | 하는 일 |
|---|---|---|
| app-01 | 10.0.20.10 | 운영 PG(데이터 9만 건), postgres S3 백업 cron·awscli, **EDH**(6379 → trap-app-01), wg0 |
| web-01 | 10.0.20.11 | 모아예약(app-01 PG 실제 연결), deploy 흔적, report-sync, **EDH**(8080 → trap-web-01), wg0 |
| db-backup-01 | 10.0.20.15 | 깊이 디코이(옮겨 온 데이터), PG + moa-notify 관문 |
| farm | 10.0.20.40 | 컨테이너 stg-01·trap-app-01·trap-web-01, WireGuard relay(센서)·edh1·edh2 |
| sensor | 투영 주소 10.0.20.30(자기 주소 아님) | 투영 → farm stg-01 |
- 미끼 엔진: `python3 baits/engine.py collect|plan|apply|verify|rotate|recall|refresh|list` (관리 쪽 venv `~/.cache/deceptive2-ctl`, 인벤토리·목적지·레지스트리는 `out/baits/`, 커밋 안 함)
- 활성 배치 9개: env_db_url(rpt_ro)·ssh_config·history·agent_session·sync_service(sync_svc)·cache_hint(web-01), aws_profile(app-01 postgres), decoy_port 6379(app-01)·8080(web-01). 제약 `baits/constraints.yml`(app-01 postgres ssh 막음 — 옛 rsync 키 삭제 결정)
- 진정성 측정: `validation/README.md` 실행법. 원자료 `out/validation/2026-11-22/`
- 로컬 전용 흔적(EC2엔 없음): VM의 `/etc/apt/apt.conf.d/01-lab-proxy`, sensor NIC의 169.254.31.1, 호스트 이름 `lt-*`

## 3. 트러블슈팅 기록 (원인 → 해결, 다음 세션이 같은 실수를 안 하게)
| 증상 | 원인 | 해결 |
|---|---|---|
| **app-01·sensor 통째로 먹통**(sshd·PG까지) | 중계용으로 **local 경로표 규칙을 pref 0→1000으로 옮김** → networkd 재시작(업데이트 때 발생)이 "외래" 규칙을 지움 → 자기 주소로 오는 패킷을 못 받음 | EDH는 정책 규칙 없는 **이중 DNAT**(EDH: 주소:포트 → 169.254.200.1 → wg0, farm: 다시 EDH 주소로 DNAT, conntrack이 되돌림). 센서도 투영 주소를 자기 주소로 두지 않음. 공통 베이스에 `networkd.conf.d/10-keep-foreign.conf`(ManageForeign*=no). **원칙: 디코이 장치는 망가져도 운영 서버가 멀쩡해야(fail-safe)** |
| 재부팅 뒤 중계 꺼짐 | 부팅 순서(데몬이 터널보다 먼저) | moa-notify 5초 자가 복구(경로·관문 규칙), farm 규칙은 wg-quick PostUp·networkd `[Route]`/`[RoutingPolicyRule]` |
| farm veth 주소가 사라짐 | networkd 기본 `80-container-ve.network`와 시작 스크립트 경쟁 | veth 설정을 networkd 파일(`10-ve-*.network`)로 |
| 투영 주소 라우팅 루프 | 컨테이너가 죽어 경로가 빠지자 farm이 LAN으로 내보냄(같은 LAN에 센서) | farm에 `blackhole X/32 metric 1000`, 시작 스크립트는 항상 exit 0 |
| VM이 응답 안 함(배너 타임아웃) | **호스트 스왑 가득**(5대, 게스트 페이지 캐시는 balloon이 안 돌려줌) | lab.sh 메모리 표(합계 약 4.4GB). ClamAV 검사 때만 2GB로 따로 |
| 스크립트 실행 중 멈춤 | SSH 세션 안에서 networkd를 바로 재시작 | `systemd-run --on-active=1 ... restart systemd-networkd`(분리) |
| masquerade 중계가 들킴 | Redis `CLIENT LIST`에 addr=EDH 자신·laddr=트랩 내부 | 주소 변환 없는 터널(이후 이중 DNAT) — 서비스는 자기·상대 주소를 말한다 |
| 측정 도구가 서버를 오염 | 용어 목록을 명령 인자로 넘김 → sudo·auditd가 기록 | 셸 내장 printf → /dev/fd. 측정·배포 파일을 서버에 남기지 않기 |
| 미끼 엔진 버그들 | 원래 히스토리 exit 줄 삭제, 고아 미끼, "맥락 사라짐" 오판, 중복 배치, PATH, 규칙 오판 3개 | 덩어리 단위 삽입, pending 먼저 기록, 자기 미끼 자리 인식, plan 중복 거름, 2단계 적용, 목적지 감사 |
| QEMU LAN | socket listen/connect 한 방향만 | 멀티캐스트 공유 LAN |
| 정책 규칙이 ARP까지 가로챔 | 센서 local 앞 규칙 | proxy ARP(로컬 L2용, NIC에 IPv4 하나 필요) |
| **투영 경로 SSH가 키 교환(`KEX_ECDH_REPLY`)에서 멈춤**(배너·작은 HTTP는 됨) — 11/23 | farm 컨테이너 시작 스크립트가 relay 터널보다 먼저 돌아 응답 경로표(120)가 비었음 → 컨테이너 응답이 main을 타고 **같은 LAN으로 바로** 나가 터널을 우회 → 센서의 SYN-ACK MSS 조정(1340)을 못 받아 클라이언트가 MSS 1460으로 큰 세그먼트를 보냄 → 터널 MTU 1380에서 버려짐. 센서는 그 LAN 주소가 없어 ICMP frag-needed도 제대로 못 돌려줌(PMTU 블랙홀). 단서: 센서 `-i relay` MSS 규칙 0건, farm `ip route get … iif ve-stg-01` = enp0s3 | 응답 경로·규칙·MSS 조정을 `wg-quick@relay` PostUp으로(터널 수명 주기), 컨테이너 유닛 `After=wg-quick@relay`. **교훈: 경로가 비면 조용히 우회한다 — 터널을 쓰는 경로는 터널이 있어야만 존재하게** |

## 4. 열린 문제 (해결해야 할 것, 우선순위 순)
1. ~~투영 경로로 stg-01에 SSH하면 키 교환에서 멈춤~~ → **11/23 해결**(아래 3절 표 마지막 줄). 지금은 SSH가 끝까지 진행, 인증 방법 `publickey`만(app-01과 같음)
2. **farm 디코이 종류 결정 대기**(사용자): A 컨테이너 유지 + 고칠 수 있는 것만 / B metal 인스턴스 VM(벤더 방식) / C EC2 인스턴스. 컨테이너 한계: `systemd-detect-virt`=systemd-nspawn(B7), auditd 불가(D4 audit 0) → 트랩·stg-01 안에선 세션 명령 기록(4번)도 안 됨
3. stg-01 루트파일시스템이 debootstrap이라 EC2 이미지와 패키지·서비스가 다름(D2·D3) → 트랩처럼 공식 클라우드 이미지 tarball로 다시(`servers/hosts/farm/trap/build.sh` 방식)
4. farm 커널을 EDH와 같은 패치·재부팅 주기로(트랩 Redis `INFO os`에 farm 커널이 보임: 147 vs EDH 149)
5. sshd `LogLevel VERBOSE`를 세 서버 공통 베이스에(CIS 권고) — retired 미끼 키 사용 탐지에 필요
6. `validation/compare.py` 규칙이 db-backup-01 역할에 고정 → 역할별 규칙(stg-01·트랩·web-01). web-01은 아직 한 번도 측정 안 함, app-01·db-backup-01도 1~3번 뒤 재측정 필요(디코이 전용 흔적: 관문·wg0·nft 테이블 등은 "목적지 탐지 장치" 예외인지 판정)
7. moa-notify 웹훅이 VM에서 가짜 주소(`127.0.0.1:9`) → 로컬 수신기(`infra/local-vm/webhook_sink.py`)로 연결해야 경보를 실제로 모음. 웹훅 실패 재시도가 감시 루프를 늦춤
8. 미끼 엔진 레지스트리 → 비공개 S3, Ansible `aws_ssm` 연결(11/28). AWS 키(T6형)는 지금 형식만 맞춘 가짜 → IAM `backup-legacy` 실제 키(권한 없음)
9. Terraform(11/28): sensor(ENI 2개)·farm(t3.medium, farm 서브넷 10.0.3.0/24)·보안 그룹(farm UDP 51820~ ← sensor·EDH, EDH 디코이 포트 ← 10.0.0.0/16), db-backup-01 보조 IP 0(반영됨), farm·EDH src/dst check 검토
10. 로컬 전용 한계: web-01 ARP에 farm이 보임(단일 LAN), 투영 응답 ARP 보조 주소
11. **병행 세션 브랜치** `worktree-bridge-cse_01X8XEfnVcaGyqMxdt6nUcCs`(시계를 2024-06으로 돌린 골든 디스크, 미병합) — 사용자 결정: **재구축 서사 유지, 병합 안 함**, 건드리지 않음. 다른 worktree `…fo917…`는 커밋 없음. 작업 전 `git worktree list`·ListAgents로 병행 세션 확인

## 5. 다음에 할 일
- **바로 다음 ①: 검사 3겹 만들기 `infra/checks/`(11/23 사용자 승인)** — 11/22 장애 대부분은 사람이 디버깅하기 전에 걸렸을 것
  1. 정적 검사(`infra/checks/static.sh`): shellcheck(servers/·infra/·validation/ 셸 — pipefail+grep -q 같은 실수), `nft -c -f`(규칙 문법), `systemd-analyze verify`(유닛), `netplan generate`, **직접 만든 린터**: ① 운영 서버용 코드에 `ip rule del pref 0`·local 규칙 이동 금지 ② 스크립트가 `dev X` 경로를 걸면 그 유닛에 `After=X`가 있거나 X의 PostUp 안이어야 함(부팅 순서) ③ `ip rule`·`ip route`를 거는 서버엔 `networkd.conf.d/10-keep-foreign.conf`가 같이 있어야 함 ④ `lab.sh` 메모리 합계 ≤ 호스트 RAM 55% ⑤ 서버에 올라가는 파일에 프로젝트 용어 없음
  2. 경로 단언(`infra/checks/paths.sh`, 배포·재부팅 뒤 자동): 설계한 경로마다 각 홉에서 `ip route get <dst> from <src> iif <if>`가 기대 장치인지(예: farm `10.0.20.11 from 10.0.20.30 iif ve-stg-01` → `relay`, EDH `169.254.200.1` → `wg0`), 터널 경로의 양방향 MSS 조정 존재·카운터>0, local 규칙(pref 0) 존재. 트래픽 없이 몇 초
  3. 공격자 시점 검사: 기존 진정성 검증 세트 + 기능별 스모크(트랩 `CLIENT LIST` 주소, 투영 SSH 끝까지, 미끼 연결 `ss -tan`, 관문 페이로드 경보)
  + 미끼 엔진 단위 테스트(`baits/tests/`: 히스토리 덩어리 삽입·회수가 원래 줄을 안 지움, plan 중복 거름, 자기 미끼 자리 인식, 회수 뒤 빈 파일 삭제)
  - 정적으로 못 잡는 것: 응용 계층 단서(Redis CLIENT LIST·커널 버전) → 3번, 실행 중 경로표 상태(부팅 순서 결과) → 2번
- **바로 다음 ②**: 원래 일정 11/25분(디코이 SSH·DB **목적지 탐지**: moa-notify sshd 감시·미끼 키 지문 A/B·DB 계정, sshd VERBOSE 공통) + **축소 감사 4번 디코이 행동 기록**(Attivo·IllusionBLACK: 세션 전체·반입 도구 수집 — 벤더 원문 먼저, 컨테이너 auditd 불가 문제와 묶임)
- 남은 축소 감사 항목과 원래 일정 매핑: 9 tar-pit·10 출발지 포렌식 → 11/27 / 8 자동 격리 → 12/1 / 7 노출 제거(자동 탐색) → 12/2 / 5 자동 블렌딩·6 Deflect → 새 범위, 마감 영향 보고 사용자 결정 / NAT 구조 → 11/28(CLAUDE.md 규칙이라 사용자 결정)
- 원래 일정: 11/26 결과 기반 감시 P0, 11/27 경보·상관분석·포렌식, **11/28 AWS 일괄 구축**(위 8·9 포함), 11/29 EC2 재측정·기준선, 11/30~12/2 오탐·시나리오, 12/3~4 보고서
- 블로그 진행 글(티스토리): 사용자 확인 필요(CLAUDE.md)

## 6. 작업 방식 (11/22 느려진 원인 → 대책)
원인: 일의 양(4~5일분), **만든 뒤 다시 만들기**(벤더·공격자 시점 확인 전에 구현), 느린 VM 루프(재부팅·다운로드·메모리 돌려막기), 결정 왕복, 긴 출력으로 컨텍스트 소모
- 구현 전에 공격자 시점 검사부터(예: `CLIENT LIST`, `ss -tan`, known_hosts, `systemd-detect-virt`)
- VM은 `lab.sh`로만. 모든 원격 명령에 `timeout`. networkd·네트워크 재시작은 `systemd-run`으로 분리
- 출력은 필요한 줄만(`grep`·`tail`·`cut`). 큰 로그·원자료는 `out/`에 쓰고 요약만 보기
- 항목마다 시간 상한, 넘으면 알림. 결정은 한 번에 모아 묻기
- 운영 서버를 건드리는 설계는 **fail-safe 먼저**(망가지면 기능만 꺼지고 서버는 멀쩡)

## 7. 벤더별 구현 현황 (11/23)
| 벤더 | 기능 | 상태 |
|---|---|---|
| Illusive | 맥락 기반 미끼 배포(US10382483) | ✅ 1번 |
| Illusive | 트랩 서버 중계(US10404747) — 운영 서버 빈 포트 → 트랩, 양보, 활성 포트만 가리키는 미끼 | ✅ 2번. ❌ 같은 특허 청구항 1의 "브라우저 미끼 → 가짜 웹사이트 트랩"(서버엔 브라우저 없음 — 대응물 정해야 함) |
| Illusive | tar-pit / 출발지 포렌식 / 노출 제거(ASM) / 디코이 안 은닉 감시 | ❌ 9·10번(11/27) / 7번(12/2) / 계획 없음 |
| Attivo | 연결 테이블 미끼(US10375110) — 핸드셰이크만 한 연결 + 페이로드 관문 | ✅ 3번(벤더 문서 귀속 정정: Illusive → Attivo) |
| Attivo | 실제 OS·골든 이미지 디코이 | ✅ db-backup-01(재구축 서사). 행동 기록(세션 전체·반입 도구)은 ❌ 4번 |
| Acalvio | 투영(센서 + 중앙 팜 + 터널) | ⚠️ 구조는 동작(센서 1·구간 1·디코이 1). 아래 8절 |

## 8. Acalvio 투영 — "가능한 수준"까지 남은 구현 (11/23 사용자 요청, 다음 세션)
- **L2 터널은 VPC에서 불가**: VPC엔 L2 브로드캐스트 도메인이 없다(ARP는 하이퍼바이저가 답하고, 패킷은 그 IP를 가진 ENI에만). 센서–팜을 VXLAN으로 이어도 투영 주소는 어차피 센서 ENI 보조 IP여야 패킷이 온다 → L2의 이점(디코이 자기 MAC, ARP·DHCP·브로드캐스트 발견에 응답)이 없다. **원본이 L2인 이유**: 온프레미스 VLAN 대상 — 센서가 VLAN을 팜까지 브리지하면 디코이가 그 구간의 진짜 L2 이웃(ARP·DHCP·NetBIOS/LLMNR/mDNS·`net view`), 센서는 주소별 라우팅 불필요. 클라우드에선 벤더도 VPC 안에 디코이를 직접 둔다 → 한계로 기록(학습 로그 후보)
- 가능한 수준으로 할 것(각각 공격자 시점 검사 먼저):
  1. **여러 구간**: public 서브넷(web-01 쪽)에도 센서 → 구간마다 투영(Acalvio "VLAN별 센서"). 센서는 ENI당 보조 IP로 투영 주소 여럿
  2. **팜 안에 서로 다른 디코이 여러 개**: 디코이 = 공식 클라우드 이미지 컨테이너(트랩 build.sh 방식), 역할 템플릿(옛 스테이징·옛 빌드 서버 등) — 사용자가 고를 것(11/22엔 stg-01만 선택)
  3. **블렌딩(규칙 기반, AI 대신)**: 미끼 엔진이 모은 주변 서버 맥락(hostname 규칙 `역할-번호`, OS·패치 수준, 열린 서비스 종류)으로 투영 디코이의 이름·서비스·배너를 자동 결정 → Acalvio "주변 이름·서비스와 섞이게"
  4. **즉석 생성·회수**: 미끼 엔진에 `projection` 유형(센서 주소 할당 → 팜 디코이 생성 → 터널 경로) — 레지스트리로 관리, 회수 시 흔적 없이
  5. 디코이 품질(컨테이너 정체·auditd)은 4절 2번(A/B/C) 결정에 따름
- 일정·상한: 마감(12/4) 안. 사용자 결정 필요 — 2번 디코이 역할, 4절 2번 A/B/C

## 9. 투영과 ARP·DHCP·브로드캐스트 (11/23 실측)
- **ARP**: 발견됨. web-01의 `ip neigh`에 투영 주소 10.0.20.30이 **센서 MAC**(52:54:00:20:00:30)으로 보인다(로컬은 센서 proxy ARP, AWS는 하이퍼바이저가 ENI IP에 대해 답함)
- **DHCP·브로드캐스트·멀티캐스트**(NetBIOS·LLMNR·mDNS·net view): VPC가 전달하지 않아 진짜 서버도 이 방법으론 발견 안 됨 → 단서 아님. L2를 못 써서 잃는 발견 경로는 VPC엔 없다
- **새 단서(L3 구현의 대가)**: 디코이 안에서 `ip link`를 보면 자기 NIC MAC이 무작위 veth MAC(da:b6:…)이라 ① 이웃의 ARP 값(센서 MAC)과 다르고 ② AWS ENI MAC답지 않다 → **시도: 컨테이너 host0 MAC을 센서(투영 ENI) MAC으로 맞춤** — 결과: 투영 접속 "SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13.20
" (라이브로 nsenter `ip link set host0 address`, 영구 반영은 farm install.sh의 컨테이너 networkd 파일 `[Link] MACAddress=`로 — 다음 세션)
- **여러 디코이를 센서 하나(ENI 하나)로 투영하면 서로 다른 "서버"가 같은 MAC**으로 ARP 캐시에 보인다(다중 주소 때와 같은 묶임) → 투영 디코이마다 ENI를 따로(t3.small ENI 3개 = 관리 1 + 투영 최대 2) — 8절 1번 여러 구간 계획에 반영할 것

## 10. 다음 세션 첫 지시 (11/23 사용자)
**8절 투영 확장 1~4를 "마저 구현"하는 것이 사용자가 원한 일이다**(기록만 하라는 뜻이 아님). 11/22 세션은 컨텍스트 소진으로 구현하지 못하고 기록만 함. 순서: 사용자에게 8절의 결정 2개(추가 디코이 역할, 4절 2번 A/B/C)를 먼저 묻고 → 1 여러 구간(센서 ENI 분리, 9절 MAC 묶임 반영) → 2 디코이 여러 개(트랩 build.sh 방식 클라우드 이미지) → 3 규칙 기반 블렌딩 → 4 미끼 엔진 `projection` 유형. 각각 공격자 시점 검사 먼저, 끝나면 학습 로그. 6절 검사 3겹과 순서는 사용자에게 확인
