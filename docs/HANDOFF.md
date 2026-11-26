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

## 11. 11/23 세션 결정 (사용자)
- 4절 2번 디코이 종류: **B — 팜 안 KVM VM**(공식 클라우드 이미지, detect-virt=kvm·auditd 동작). 로컬은 farm 중첩 KVM(/dev/kvm 있음), AWS는 metal 팜(또는 중첩 가상화 지원 타입 — 확인 필요)
- 8절 2번 추가 디코이 역할: **dev-01 옛 개발 서버**(가상 개발자 2명이 쓰던 서버)
- 순서: **경로 단언(`infra/checks/paths.sh`) 먼저** → 투영 확장 1~4(각각 공격자 시점 검사 먼저) → 정적 린터·단위 테스트
- 로컬 여러 구간: **LAN 2개 + 라우터 VM**(public 10.0.21.0/24 = web-01, internal 10.0.20.0/24 = app-01·db-backup-01·farm, 라우터가 각 .1 — VPC 라우터 역할, 로컬 전용). 센서는 구간마다 NIC. web-01 주소 바뀜 → 미끼·EDH 다시 적용. 메모리 때문에 시험은 필요한 VM만 켜서
- **11/23 진행(이 세션)**: ① 경로 단언 `infra/checks/paths.py` + `paths.local.txt`·공격자 시점 `attacker.local.txt`(같은 실행기) ② 중계 L3 단서 제거(TTL 홉 보정·터널 MTU=구간·MSS 조정 제거, 학습 로그) ③ **팜 디코이 VM 도구** `servers/hosts/farm/guest/`(guest.sh create/offline/seal/online, guest@.service, guest-up(fail-closed: 표 120 unreachable)), 제어 쪽 `infra/local-vm/farm-guest.sh create|role <이름>`. stg-01 debootstrap build.sh 삭제, role.sh는 오프라인 디스크용으로. farm install.sh는 relay만(인자 = 센서 공개키 하나) ④ 구간 분리 준비: vm.sh `VM_LAN_EXTRA`, lab.sh 표(LAN int/pub, router 행, web-01 → 10.0.21.11, 센서 추가 NIC pub:30), `infra/local-vm/router.sh`(VPC 라우터 흉내, TTL 보정). **아직 적용 안 함**(VM 재시작 필요) ⑤ 블렌딩 `baits/blend.py` + `projection.yml` + `baits/tests/test_blend.py`(7개 통과), 수집기에 platform(커널·OS·패키지)
- 구간 분리 적용 순서(남음): router up → router.sh → web-01 재시작(pub) → sensor 재시작(NIC 추가) → app-01·db-backup-01·farm `lab.sh up`(경로 추가) → trap-web-01·moa-notify·미끼(collect→refresh), destinations.yml `lan_cidr: 10.0.20.0/23` → paths/attacker 명세 주소 갱신
- 주의: farm 탭·veth에 게이트웨이(.1)를 두면 farm이 LAN에서 라우터 ARP를 가로챔 → 169.254.31.2/32 + proxy ARP로 바꿈(guest.sh·trap build.sh 반영, 라이브 trap은 다시 build 필요)
- **dev-01 서사(11/23 사용자 결정)**: 구축 2024-09-02(이서연 합류) ~ 마지막 사용 2025-05-12(stg-01과 같은 날 — 2025-05부터 각자 노트북 로컬 개발로), 개발 DB = 2025-05-12 운영 사본(make_carryover.py --dump-at), 다른 서버 흔적은 git remote(staging deploy@stg-01, production deploy@web-01) + known_hosts만(개인키 없음 — 새 자격증명 미끼 아님)
- 블렌딩 결과(로컬): stg-01 → pub 10.0.21.12(웹 옆), dev-01 → int 10.0.20.11(DB 옆). 이전 수동 stg-01(10.0.20.30)은 삭제
- **3중 중첩 불안정(로컬 전용 문제)**: farm 안 KVM 디코이(Hyper-V → WSL2 KVM → farm KVM)에서 게스트 메모리 손상 — ① balloon free-page-reporting 켜면 apt 중 Oops ② 끄고 vCPU 2면 종료 때 soft lockup(xas_descend 무한). 시도: 디코이 vCPU 1 + farm vCPU 4(lab.sh, destinations `farm.guest_cpus: 1`). AWS metal 팜은 1단 KVM이라 해당 없음(그땐 vCPU 2). 안 되면 대안: 로컬만 디코이 VM을 farm 밖 L2로(사용자에게 물을 것)
- **11/23 세션 끝 상태**: 트랩 2개는 새 구조(web-01 10.0.21.11, 링크 로컬 veth)로 다시 배치, 공격자 시점·경로 단언 stg 관련 외 전부 통과. **디코이 VM 투영은 로컬에서 못 띄움** — 3중 중첩에서 vCPU 1로도 커널 panic(131초, `Attempted to kill init`). stg·dev 배치는 회수함(레지스트리 recalled, 센서 투영 목록 비어 있음). farm-guest.sh 삭제(엔진이 유일한 경로)
- **다음 세션 첫 결정(사용자)**: 로컬 디코이 VM을 어디서 돌릴지 — ① 로컬만 디코이 VM을 farm 밖(호스트의 L2 VM)으로, farm과는 전용 LAN(socket)으로 이어 farm에서 ve-<이름>으로 보이게(호스트 sudo 없음 → 디스크 마운트·역할 단계는 farm이 nbd를 못 씀 → 역할 적용을 cloud-init·게스트 안으로 옮겨야 함) ② 로컬 검증은 컨테이너로 두고 VM은 11/28 AWS metal 팜에서 처음 검증 ③ AWS에서 바로 metal/중첩 지원 인스턴스로. 검사 명세(inside.local.txt)는 준비돼 있음
- 엔진 배치 후 남은 확인: inside 검사(detect-virt=kvm, auditd, MAC, sr1 없음, user-data 봉인, 스냅숏 설정 제거, 커널 = 이웃 149), dev 역할 첫 실행(미검증), 투영 디코이의 목적지 탐지(moa-notify — 11/25 일정과 묶음)

## 12. 11/23 오후 — 지금 상태 (위 11절의 "다음 세션 첫 결정"은 해결됨: 로컬 팜 = WSL2)
- **구조**: 팜 = WSL2 자신(`infra/local-vm/farm-host.sh up|down|check|status`, farm VM 없음). 랩 VM: router·app-01·web-01·db-backup-01·sensor. 환경 값은 `infra/env/local.yml`만 → `python3 infra/env/render.py local`(프로필 고치면 반드시 다시 — 엔진·검사가 해시로 막음)
- **안전 규칙**: WSL2 복구 `docs/local-farm-recovery.md`(부팅 자동 시작 없음 → `wsl --shutdown`이 완전 복구). 랩 VM 재부팅은 `lab.sh reboot`만(VM 안 reboot 금지 — cloud-init이 호스트 키 재생성, 11/23 app-01). 홈 디렉터리 와일드카드 삭제 금지
- **투영 디코이**: 엔진이 블렌딩→배치(`engine.py apply`), 켜고 끄기 `engine.py feature projection|trap on|off|status`, 디코이에 회사 표준 moa-notify `engine.py decoy-agent <템플릿>`. stg-01(pub 10.0.21.12, 1024MB)·dev-01(int 10.0.20.11, 896MB) 모두 배치, moa-notify 포함, **검사 4종(paths·attacker·inside·lab) 전부 통과**
- **검사**: `infra/checks/static.sh`(배포 전), `farm-host.sh check` = paths·attacker·inside·lab 명세(환경 중립, 진짜 서버와 그 자리 비교)
- **진짜 서버**: app-01·web-01 11/23 full-upgrade(커널 151). app-01 SSH 호스트 키는 11/23 11:39 재생성됨(옛 키 복구 불가 — 그 키를 기억하던 미끼·디코이는 없음 확인), 시각은 2024-06-12로 다시 맞춤
- **투영 켜고 끄기 시험(11/23 통과)**: off → 센서 투영 목록 비고 relay 없음(센서·팜), 디코이 VM 0대, 공격자 자리에서 응답 없음, 트랩은 그대로 통과 / on → 같은 주소·같은 NIC MAC으로 되살아나 검사 4종 통과
- **남은 일(순서)**: ③ 11/25 목적지 탐지: 팜 쪽 접속 경보(Acalvio — 디코이 밖 탐지, 특허 원문 확인함) + 기존 계획 ④ 웹훅 설정 통일(세 서버 값이 다름, 4절 7번) ⑤ 디코이 이후 업데이트 방식(unattended 켤지) — 사용자 결정 대기 ⑥ 11/28 AWS: aws.yml 채우기, EC2 모양·IMDS(local-aws-parity 4절), 팜 = metal 또는 C8i/M8i/R8i 중첩
- 알려진 한계: 디코이 /proc/meminfo 4kB 차이, 디코이 감사 로그에 구축 당일 기록(진짜 서버는 회전), 진짜 랩 VM엔 옛 cloud-init 인스턴스 디렉터리가 여러 개(디코이는 하나), 디코이는 빌드 뒤 인터넷 없음

## 13. 11/23 저녁 — 벤더 기술 스위치(사용자 원칙: 끄면 그 기술의 방식이 환경에서 전부 사라짐, 자체 설계는 항상 켬)
- `python3 baits/engine.py feature <breadcrumbs|trap|conntable|projection> on|off`, `feature - status`
  - breadcrumbs = Illusive 맥락 미끼 T1~T6 / trap = Illusive 트랩 서버(빈 포트 중계 + cache_hint) / conntable = Attivo 연결 테이블(report-sync의 핸드셰이크 연결 + db-backup-01 페이로드 관문) / projection = Acalvio 투영
  - 항상 켬: db-backup-01(자체 설계 옛 백업 서버 디코이 — "실제 OS 디코이"는 특정 벤더 기술이 아님), moa-notify, 랩 장치
  - report-sync는 두 기술을 싣는다: 미끼 계정(Illusive T5) + 연결(Attivo) — 4가지 조합(bait_types SyncService.ops crumbs·conn), 디코이 이름 풀이(hosts 줄)는 T1과 공유
- 검사: `infra/checks/features.spec`({feat:X}/{nofeat:X} 자리표시자 — 켜면 있어야, 끄면 없어야), `farm-host.sh check`가 5종(paths·attacker·inside·lab·features)
- 스위치마다 끄고 켜기 시험 통과(11/23). 고친 결함: moa-notify가 끈 감시(관문·트랩 중계)의 커널 규칙을 남김 → 시작 때 정리(우리 흔적이 있을 때만 — fail-safe), 엔진 unit 작업이 파일을 바꿔도 재시작 안 함 → ctime 비교로 재시작
- `lab.sh up`은 VM을 동시에 켬(하나씩 → 동시, 출력은 VM 순서대로)
- WSL이 저녁에 재시작됨(원인 Windows 쪽) → 설계대로 디스크·레지스트리만 남고 깨끗이 내려감 → `lab.sh up all` + `farm-host.sh up`으로 복구, 검사 통과
- **11/23 밤 결정(사용자)**: 로컬 관리 접속 경보 소음은 그대로 두고 11/30 오탐 단계에서 / 경보 수신기(webhook_sink) 연결·웹훅 통일을 지금(원래 11/27) / 디코이 이후 업데이트 = **주기적 재블렌딩**(이웃 apt 이력이 바뀌면 팜이 꺼진 디스크에서 같은 스냅숏으로 — 디코이에 바깥 길을 열지 않음)

## 14. 11/23 밤 — 디코이 목적지 탐지(원래 11/25) + 경보 수신
- **경보 수신기**: `lab.sh`가 호스트에 `webhook_sink.py`(127.0.0.1:9099 → `~/.cache/deceptive2-vm/webhook.jsonl`)를 띄움. 웹훅은 환경 프로필 `notify`(랩 VM은 10.0.2.2:9099, 팜은 127.0.0.1:9099). `engine.py notify-config`로 세 서버 통일(HANDOFF 4절 7번 해결)
- **디코이 SSH 탐지**: moa-notify `sshd` 감시(auth.log, 접속 하나 = 경보 하나 — 로그인 뒤 OpenSSH가 세션을 "User child is on pid N"으로 넘기는 것까지 묶음), 시도한 키 지문 포함. 디코이만 켬(회사 서버는 같은 모양으로 꺼 둠). 공통 베이스 `LogLevel VERBOSE`(`base/install.sh ssh` — 실패한 키 지문도 남김)
- **지문 → 미끼**: `engine.py whois <값>` — 서버 밖에서 레지스트리로(active·paused·retired)
- **팜 쪽 탐지(Acalvio)**: relay PostUp nft `proj_watch`(새 연결 로그, 초당 20) + 팜 `relay-notify`(같은 코드, `projection` 감시 — 디코이 이름·진짜 출발지). relay와 수명 같음(Wants·PartOf). 투영 디코이 안 moa-notify는 바깥 길이 없어 경보를 못 보냄 → 탐지는 팜(설계대로)
- **탐지 검사** `infra/checks/detect.py`(farm-host check에 포함): 5경로(디코이 DB·SSH 미끼 키·투영 stg·dev·트랩) 모두 0.6~1.4초(기준 60초)
- 고친 것: 디코이 `/backup/.ssh` 디렉터리 시각이 미끼 재기록 때 오늘로 바뀜 → 적용기가 상위 디렉터리 시각 보존, nft 예약어 체인(`fwd`) 정적 검사
- 남은 일: ~~주기적 재블렌딩~~(15절), 디코이 세션 명령 첨부(11/27 계획), 출발지 포렌식(11/27), 관리 접속 소음 억제(11/30)

## 15. 11/23 밤 — 주기적 재블렌딩 = 시점 고정 apt 미러(사용자 결정)
- **구조**: 디코이는 이웃처럼 **자기 unattended-upgrades**로 업데이트(재부팅 없음, 같은 흔적). 팜 `relay-mirror`(`servers/hosts/farm/guest/mirror.py`, 169.254.31.2:3144)가 디코이 apt 요청을 받아 **이웃과 같은 시점의 snapshot.ubuntu.com**에서 돌려줌
  - 가로채기: relay PostUp nft `proj_mirror`(`ve-*` 들어온 것 중 프로필 `farm.guest.mirror_intercept` — 로컬 `10.0.2.2:3142`(디코이의 lab 프록시 설정), AWS `*:80`(투명)) → DNAT
  - 허용: archive·security.ubuntu.com `/ubuntu/`의 GET·HEAD만, 나머지 403(디코이가 인터넷 통로가 되지 않게). 요청은 모두 journal(공격자의 apt 사용도 흔적)
  - 시점: 출발지 → `/etc/guest/<이름>.env`의 `SNAPSHOT`(일반)·`SNAPSHOT_SECURITY`(보안 저장소). 요청마다 다시 읽음
- **재블렌딩** `engine.py reblend [--no-collect]`: 이웃 맥락 다시 수집 → `blend.segment_platform` → 바뀌면 팜 env의 시점 값만 바꿈 + 레지스트리 `reblended` 이벤트. 디코이는 다음 unattended 실행 때 따라감
  - 확인: stg-01 보안 시점을 일부러 옛 값으로 → reblend가 이웃 값으로 되돌림. 디코이 `apt-get update` = 미러 경유, 이웃 시점, 업그레이드 대상 0
- **한계**: 이웃이 손으로 full-upgrade하면(`apt_manual_upgrade = after`) 디코이 unattended는 보안 외 업데이트를 안 따라감 → reblend가 경고만(다시 만들지 여부는 그때 판단). 주기 실행: 로컬은 명령만(WSL 자동 시작 금지), AWS는 팜 timer — 11/28 구축 때
- 남은 일: 11/27(디코이 세션 명령 첨부·출발지 포렌식·경보 연관), 11/28 AWS 구축, 11/30 오탐

## 16. 11/23 밤 — 11/26분 앞당김: 미끼 열람 감시 + 결과 기반 감시 P0(사용자: 11/26 먼저, 그다음 11/27 벤더 기술)
- 사용자 결정(11/23): 다음 벤더 기술은 **계획 안 것부터**(① Illusive 출발지 포렌식 ② Attivo·IllusionBLACK 디코이 행동 기록 → 여유 시 ③ tar-pit, ④ 자동 격리 12/1·⑤ ASM 12/2·⑥ CloudTrail 11/28은 계획 날짜). 행동 기록의 투영 디코이 = **팜이 디코이 디스크를 읽기 전용으로 읽음**(게스트 흔적 0, 일관성 먼저 실측), 포렌식 = **관리 쪽 상관기**(로컬 호스트 → AWS Lambda+SSM 11/29), 스위치 = **기술마다 따로**(forensics·engagement·tarpit)
- 열람 감시 = **자격증명 위치 일반 규칙**(사용자 결정 — 미끼별 규칙은 `auditctl -l`로 미끼 위치 노출). 결과 감시 P0 + **사용자 crontab 추가**(사용자 결정, 범위 변경 기록)
- 구현: `servers/base/audit/60-persistence.rules`, `account-rules.sh`(서버 계정·서비스에서 규칙 생성, 꺼진 디스크도), `install.sh audit`, moa-notify `audit` 감시(테스트 7개 추가, 27개), `notify-config`가 모든 서버 켬, 투영 디코이는 `engine.py decoy-agent`(`guest/audit.sh`) — 새 디코이는 빌드의 역할 단계 뒤에 자동
- 검사: inside.spec 감사 규칙 비교를 "공통 부분 = app-01 + 계정 규칙 존재"로 바꿈. detect.py 3경로 추가(T1 .env·T6 키 파일·authorized_keys) → 8경로 모두 1.2초 이내. farm-host check 전부 통과
- **첫 오탐 실측(11/30 재료)**: SSM 에이전트가 `/root/.aws/credentials`를 약 30초마다 읽음(서버당 20분에 44건) + CloudWatch 에이전트. 그 파일은 로컬 랩 전용(onPremise 모드 키) → EC2에선 없을 것, 11/28 확인. 1분 한도(30건)는 아직 안 넘음
- 트러블슈팅: `auditctl -l`이 `exe!=`를 `exe=`로 보여 줌(규칙에 안 씀), path·dir 규칙은 `-w` 형식으로 보임. `ausearch`는 표준입력이 파이프면 그걸 읽음(`--input-logs </dev/null`). 꺼진 디스크의 `/etc/systemd/system` 별칭은 호스트 경로를 가리키는 절대 심볼릭 링크 → 건너뜀
- **서버에 남은 프로젝트 용어(CLAUDE.md 위반, 이전부터)** 발견·수정: `/opt/moa-notify/moa_notify.py` 주석(디코이·미끼·트랩·벤더 이름 — 세 서버와 투영 디코이 모두), `/etc/ssh/sshd_config.d/50-loglevel.conf` 주석, `/etc/wireguard/wg0.conf`(edh-tunnel.sh heredoc 안 주석), web-01 `/home/ubuntu/servers`(11/20 업로드 사본 — 모두 git에 있어 삭제, 홈 시각 복원). 근거·설명은 README로, 팜 감시 클래스 `TunnelIn`·경보 source `터널`. 재발 방지: static.sh 용어 검사(서버에 남는 파일) + inside.spec 5대 용어 검사(자기 hostname 줄 제외)
  - 실수: wg0.conf 시각 보존용 임시 사본을 `/root`에 만들어 web-01·app-01 `/root` 시각이 오늘로 바뀜(원래 값 모름 — 꾸미지 않고 기록)
- **열린 문제(11/28 AWS hostname 설계 때)**: 로컬 db-backup-01의 hostname이 랩 VM 이름 `lt-decoy`(→ /etc/hostname, 호스트 키 주석 `root@lt-decoy`, CloudWatch 에이전트 파일). app-01은 `lt-app`. 로컬 VM 이름을 바꾸면 cloud-init hostname 처리(11/23 호스트 키 사고 경로)를 건드림 → 지금은 기록만. AWS에선 hostname을 서사 이름으로 정하고 호스트 키 주석까지 확인할 것
- 검사가 남기는 소음: 용어 검사·탐지 검사가 root로 자격증명 파일을 읽어 `감사` 경보가 남(측정 흔적 — 랩 관리 세션 auid=ubuntu로 구별)
- 다음: 11/27 ① 출발지 포렌식(관리 쪽 상관기) ② 디코이 행동 기록(db-backup-01은 moa-notify가 user-cmd 첨부, 투영 디코이는 팜 디스크 읽기)

## 17. 11/23 밤 — 미끼 서사 점검(사용자: "각 미끼가 왜 그 자리인지, 말이 안 되면 고쳐")
- 기술 선택 이유·안 고른 이유, 미끼별 서사·고친 것: `docs/05-design-decisions.md` 22·23절
- 고친 것: T4 히스토리 오염(11블록 제거, 세션 방식 교체), T2 시각(같은 초 → 순서대로), T3 위치, T5 주석·시각, T6 날짜(2024-06 → 2025-09-16), 디코이 authorized_keys 시각·`from=` 옛 주소, 적용기 `/root` 임시 파일 → `/run`, 상위 디렉터리 시각 보존(바꿔치기 버그 포함) + 단위 테스트 5개
- 확인: breadcrumbs 끄고 켜기 전후 시각·히스토리 차이 0, farm-host check 전부 통과, detect 8경로
- 사용자 결정 대기: IAM 사용자 이름 `backup-legacy`(05 23절 끝)
- 기록만: web-01·app-01·디코이 `/root` 시각은 오늘(원래 값 모름)


## 18. 다음 세션 첫 순서(11/24 사용자: "내일 마저")
1. 11/27분 ① 출발지 포렌식(관리 쪽 상관기, 스위치 `forensics`) → ② 디코이 행동 기록(db-backup-01 = moa-notify user-cmd 첨부, 투영 디코이 = 팜이 디스크 읽기 전용 — 일관성 먼저 실측, 스위치 `engagement`) → ③ 침투 체인 상관분석 → ④ 시나리오 1·3 로컬 리허설·기준선 정상 작업 스크립트
2. 11/28 전 미리: 서울 리전 metal/중첩 지원 인스턴스(C8i·M8i·R8i) 가능 여부, 결정 대기 2개(IAM 사용자 이름 `backup-legacy` 유지 여부, AWS hostname 정하는 법 — 로컬 `lt-decoy`)
3. 블로그 진행 글(05 22·23절이 글감)
- 랩 상태: VM 5대 + WSL 팜(디코이 stg-01·dev-01) 켜져 있음. WSL이 재시작되면 `lab.sh up all` + `infra/local-vm/farm-host.sh up`(sudo 없이 — 안에서 sudo를 부름. `sudo`로 부르면 HOME=/root라 venv를 못 찾음, 11/24)

## 19. 11/24 — 출발지 포렌식(11/27분 ①, Illusive US10382484) 완료
- 사용자 결정: 범위 = 벤더(P 특정 + P 활동 기록) + 계획 스냅숏 5종 / 미끼 열람(감사) 경보도 그 서버에서 수집 / 로컬 전달 = SSH 표준입력·tty 없음 / tar-pit = 실측 뒤 결정
- 구현 `forensics/`(README에 구조·공격자 시점 흔적): `correlate.py watch`(관리 쪽, 수신기 따라가기, 스위치 `forensics`), `collect.py`(표준입력, /proc만으로 소켓→P, O_NOATIME), `config.yml`(추적 300초·SSM/CloudWatch 억제), `scenario.sh`(회귀 5경로). 프로필 `access.run_py`(AWS는 11/29 SSM)
- 실측(학습 로그 11/24 표): P 특정 0.6~1.2초. **짧은 연결(투영 SSH 인증 실패·디코이 PG 실패)은 수집기 도착 전에 끝나 P를 놓침**(TIME-WAIT만 남음). 미끼를 먼저 연 공격자는 세션 추적이 먼저 걸려 이후 명령이 다 기록됨(psql에 미끼 비밀번호까지 — out/는 커밋 안 함)
- 공격자 시점: ps에 수집 인자(공격자 pid)가 보이던 것 수정 → `python3 -`만. 남는 것: root python3 프로세스(세션 끝까지 ≤300초), auth.log 관리 로그인 + sudo 줄, 감사 로그의 last·who
- 상관기는 로컬에서 손으로 켬(`python3 forensics/correlate.py watch` — 자동 시작 없음, WSL 원칙)
- tar-pit(사용자 결정): **PG만 `auth_delay` 3초**(공통 베이스 `50-auth.conf`, app-01·디코이 같게) → 디코이 PG 실패 경로 P 특정. SSH 공개키 실패는 OpenSSH 9.6에 지연 수단 없음(한계)
- 즉시 경보(사용자: "시중 솔루션을 따르면 그것에 맞게"): moa-notify PG·sshd `immediate` — 접속 첫 줄에서 "접속 시작"(Illusive forensic alert module). 스위치 `forensics`가 `notify-config`로 세 서버 값을 맞춤. 관문을 꺼도 PG 경로 P 특정
- 포렌식 억제 = 실행 파일 + auid unset(SSM·CloudWatch·**ClamAV 03:17 검사** — 사용자 지적, 실측은 기준선 때)
- **회귀 수정**: 60ac16f부터 엔진 `run` 작업이 빈 스크립트를 돌리고 성공 처리(쓰기 줄이 주석 안). 11/23 22:44 이후 run 작업(투영·트랩 스위치, decoy-agent 등)은 실제로 안 돌았음 — 11/24 farm-host check 전부 통과로 현재 상태는 정상 확인. 단위 테스트 추가
- 회귀 결과(scenario.sh): 처음엔 투영 SSH 인증 실패만 P를 놓침 → 사용자 지적 후 **둘 다 고침**: ① 수집기 사후 복원(감사 execve에서 목적지 주소·이름을 쓴 명령 → 죽은 P·세션) ② 팜 연결 tar-pit(`servers/hosts/farm/tarpit.sh`, relay 출구 SYN+ACK만 2초, `/etc/relay/tarpit.ms`가 있을 때 PostUp, 스위치 `forensics`가 `engine.tarpit_apply`로 켜고 끔, 값 `forensics/config.yml tarpit_ms`). 이제 다섯 경로 모두 P 특정 0.57~0.9초. 대가: 투영 디코이 첫 연결 2.2초(단서 — 진정성 측정 때 비교)
- features.spec에 forensics 4줄(즉시 경보·팜 지연 있음/없음)
- 다음: ② 디코이 행동 기록(engagement) → ③ 침투 체인 상관분석(포렌식 사건 + 미끼 whois + 디코이 세션을 한 체인으로, TIME-WAIT만 남은 사건을 같은 서버의 추적 세션 명령과 시각으로 잇기) → ④ 시나리오 1·3 리허설

## 20. 11/24 밤~11/26 — 디코이 행동 기록(Attivo engagement) 완료 + 감사 규칙 회귀
- 1단계(11/24, `6663550`): 공통 감사 규칙 `user-file`(로그인 세션이 만든·옮긴 파일, 사용자 위치 + 계정 홈), moa-notify `sessions` 감시(db-backup-01만 켬 — 세션 명령·파일 내용/해시, PrivateTmp 우회 `/proc/1/root`)
- **회귀(11/26 발견·수정 `b2dd0e3`)**: `55-user-files`가 `60-persistence`보다 먼저 걸려 `/root/.ssh/authorized_keys` 쓰기가 persistence 경보를 안 냄(syscall 규칙은 첫 매치 key만) → `70-user-files`로, 계정 규칙 파일 안에서도 user-file 줄은 맨 뒤. 투영 디코이 `decoy-agent`는 이제 저장소 감사 규칙 전부(50·60·70)를 넣음(전엔 60·61만 → 11/24 규칙이 디코이에 없었음)
- 2단계(11/26, `673e245`): 팜 relay-notify 새 감시 `guest_sessions` — 투영 연결이 온 디코이만 5초마다 디스크를 `qemu-nbd -s`(임시 층) + 저널 재생 마운트로 읽어 감사 로그를 이어 읽고 LoginSessions로(경보 host = 디코이 이름, `collector: farm:disk`), ve-<이름> pcap(`/var/lib/relay-engage/pcap/<이름>/시간.pcap`, 손님당 512MB). 스위치 = 팜 `/etc/relay/engage`(재시작 없음). 실측·막힌 점은 학습 로그 11/26 두 항목
- 공격자 시점: 디코이 안 변화 0. 대가 = 지연(세션 끝 뒤 4~14초), 메모리에만 있는 것은 못 봄
- **사용자 결정 대기**: db-backup-01(팜 밖 진짜 EC2)의 "디코이 밖 트래픽 녹화" = AWS VPC Traffic Mirroring(11/28)을 할지. 서버 안 녹화는 디코이 전용 흔적이라 안 함
- 다음: ④ 시나리오 1·3 리허설·기준선 정상 작업 스크립트 → 11/28 AWS

## 21. 11/26 — 침투 체인 상관분석(`7fd7a13`) 완료
- `forensics/chain.py`: 열쇠 = **출발 서버 + 로그인 세션(auditd ses)**. 미끼 열람·출발지 행동은 ses를 알고, 디코이 접촉은 출발 IP:포트만 아니 같은 서버의 최근 체인에 붙이고, 포렌식 사건이 그 소켓 주인 P의 ses를 알려 주면 그 체인으로 옮긴다. 미끼 ID → 털린 위치는 레지스트리(`whois`)로
- 고친 결함: **출발지 포렌식 수집기 자신**이 사후 복원 중 `~deploy/.ssh/config`를 읽어 "미끼 열람" 경보를 만들고 곁가지 체인이 됨 → `correlate.py`가 수집기 pid를 `out/forensics/collectors.jsonl`에 적고 체인이 거름
- 남은 한계: 같은 서버에서 몇 초 안에 여러 세션이 디코이를 건드리면 포렌식 없이는 IP만으로 못 가름(학습 로그 11/26)
- 단위 테스트 5개(`forensics/tests/test_chain.py`), static.sh에 추가

## 22. 11/26 — 시나리오 1·2·3 로컬 리허설 + 기준선 정상 작업 스크립트 완료
- **사용자 지시**: "하던 거 마저. 이게 보안적으로 위험하다고 인식되나 봐 — 그 부분만 빼고." → **초기 침투(T1190 웹 RCE)는 재현 안 함**(커버리지 표에서 "탐지 대상 아님(전제)"), **실제 익스플로잇·멀웨어·크리덴셜 덤퍼 안 씀.** 탐지가 보는 관측치만 평범한 명령으로 재현(기존 `forensics/scenario.sh`와 같은 방식)
- `scenarios/scenario1.sh`(웹침투→횡적이동, P0 핵심)·`scenario2.sh`(backup-legacy 키, 로컬은 호스트 1차만)·`scenario3.sh`(봇 행동 안전 재현)·`run.sh`(상관기 켜고 돌린 뒤 경보 source별 ○/✗ 판정 + `chain.py build`)
- **시나리오1 결과**: 기대 탐지 8종(감사·포트·sshd·세션·postgresql·터널·포렌식·체인) 모두 ○, **체인 하나로 묶임** — 털린 미끼 env_db_url·cache_hint·ssh_config(@web-01) → 트랩(app-01:6379) → 디코이(backup) → 투영, 계정 backup/rpt_ro, 디코이 명령 9개, 포렌식 사건 다수, 미끼 ID→털린 위치 web-01. 시나리오2 = 감사(backup-legacy 열람) ○. 시나리오3 = engagement 봇 세션(명령 15개·파일 3개) + P0 지속성(디코이 backup authorized_keys 쓰기) ○
- **고친 것**: ① 시나리오1 ④단계 `ssh`가 heredoc 세션 stdin을 삼켜 ⑥·투영이 안 돌던 것 → `ssh -n`(학습 로그 11/26). ② ld.so.preload·cron.d는 `60-persistence` 규칙만 있고 건드리는 검사가 없어 미검증 → `infra/checks/detect.py`에 안전한 생성·삭제 케이스 2개 추가(이미 있으면 안 건드림). 봇의 루트 지속성 시도는 `sudo -n`으로 즉시 거부(시도만 engagement 기록)
- **기준선**: `scenarios/baseline/run-app-01.sh [배수]` — app-01.md A1~A14를 "48시간 상당 횟수 × 배수"로, 작업별 시각을 `out/baseline/`에. A9 clamscan·A10 nmap은 `BASELINE_HEAVY=1`일 때만(OOM). **11/29 저녁 실행**, 11/30에 "예상 오탐"과 비교. web-01·db-backup-01 목록은 11/29 확정
- 검증: static.sh·`farm-host check`(paths·attacker·inside·lab·features·detect) 전부 통과, 디코이 흔적 되돌림(잔여 0)
- **안전·한계 기록**: 디코이에 잠깐 쓴 미끼 줄은 시나리오 끝에 제거. 미끼를 안 건드리고 지나가는 공격자는 안 걸림(위생이 디셉션과 경쟁 — 변경 F). detect.py 디코이 SSH 케이스가 시나리오3 직후 디코이 부하로 한 번 60초 초과 → 재실행 1.2초(일시적)
- **다음**: 11/28 AWS 일괄 구축(HANDOFF 4절 8·9, 시나리오2 CloudTrail 2차, 시나리오3 VPC Traffic Mirroring 결정, hostname 설계). 11/29 EC2 재측정 + 저녁 압축 기준선 시작. 결정 대기: IAM 사용자 이름 `backup-legacy` 유지 여부, AWS hostname(로컬 `lt-decoy`)

### 22a. 11/26 오후 — AWS 전 점검(진정성 재측정 + 서울 리전)
- **진정성 재측정**(db-backup-01 vs app-01, 11/22 이후 처음 — validation/README 11/26 항목): 자동 층 디코이 전용 단서 **여전히 0**(S1·S2 공통, E1·E2 바이트 동일, B7 kvm). 사람 층 "단서" 11개는 모두 ①compare.py 역할 고정 한계(4절 6번) ②시나리오 라이브 연결(C4) ③로컬 커널 드리프트(D2 147 vs 151 — AWS 일괄 빌드 땐 사라짐) ④설계 허용 장치(D6 15432=127.0.0.1 관문) ⑤[로컬] 이름/측정 오염. **꼭 고칠 진정성 버그 없음**
- **tar-pit 단서 실측(신규)**: 투영 디코이 첫 접속 **2.22초** vs app-01 0.03초 — 포렌식 P 포착의 대가(사용자 승인 설계), 기록된 한계. db-backup-01은 tar-pit 없음. **사용자 확인 필요**: 이 2.2초를 한계로 둘지(현재) 조정할지
- **서울 리전(ap-northeast-2) 중첩 가상화**: C8i·M8i·R8i에서 전 리전 지원(2026-02~03 출시, 추가 요금 없음, 시작/정지 상태에서 CPU 옵션 `NestedVirtualization=enabled`). **서울 명시 출처는 못 찾음 → 11/28 콘솔/CLI로 최종 확인.** 성능 민감하면 metal 권장, hibernation 불가. aws.yml `farm.instance_type` 후보 = metal 또는 C8i/M8i/R8i
- **깨끗한 역할별 진정성 숫자(투영·web-01 포함)는 compare.py 역할별 규칙(4절 6번)이 있어야** — AWS에서 전 역할 한 번에 재측정(11/29)이 효율적. 지금은 역할 규칙을 안 만듦(사용자 결정 대기)

### 22b. 11/26 결정(사용자 "그렇게 하자" — 근거 기반 기본값으로 잠금, 되돌릴 수 있음)
11/28 AWS 구축이 안 막히게 대기 결정 4개를 기본값으로 확정. 틀리면 그때 바꾼다.
1. **IAM 사용자 이름 `backup-legacy` 유지.** 레지스트리·docs·서사에 이미 엮임, "정리 안 된 옛 사용자"를 이름이 말함(부주의한 관리자가 쓸 법함). 변경 안 함
2. **AWS hostname = 역할 이름 그대로**(web-01·app-01·db-backup-01·sensor·farm). `lt-*`는 QEMU 랩 아티팩트. 11/28에 ① /etc/hostname ② SSH 호스트 키 주석(`root@<hostname>` — 로컬 `lt-decoy` 였음, 16절) ③ CloudWatch 에이전트 파일의 호스트 이름을 서사 이름으로 맞추고, 호스트 키 주석까지 확인
3. **시나리오3 VPC Traffic Mirroring = 보류**(핵심 구축엔 안 넣음, 여유 시 보강). 성공 기준 요구 안 함, db-backup-01 engagement는 서버 안 moa-notify sessions로 이미 됨. 디코이 밖 녹화(Attivo BOTsink식)는 열어 둠 — 디코이 전용 흔적 없는 깨끗한 방식이라 나중에 추가 쉬움
4. **tar-pit 2.22초 = 한계로 유지.** 사용자 승인 설계(11/24), 포렌식 P 포착의 대가. 낮추면 P 포착 신뢰도↓. 투영 디코이 첫 접속만 영향, 이후 정상. 실제 공격자가 접속 시간 비교로 드러낸 사례가 나오면 재검토
### 22c. 11/26 밤 — Terraform 다시 씀(`infra/terraform/README.md`)
- 11/21 뼈대 → 지금 설계: farm 서브넷, sensor(관리 ENI) + **투영 ENI 모듈**(주 IP = 투영 주소, 디코이마다 ENI), farm(**중첩 가상화** `cpu_options.nested_virtualization`, metal이면 끔), EDH 트랩 포트 SG, backup-writer 역할(app-01)·backup-legacy 사용자(권한 0, **키는 TF 밖**), 백업 버킷(30일 만료)·운영 버킷(버전), CloudTrail(읽기+쓰기) + EventBridge(`ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS` — 읽기 전용 `sts get-caller-identity`도) + 웹훅(선택)
- provider 5.100 → **6.74**(중첩 옵션이 6.x에만 — 스키마로 확인), random 3.9.1. `network_interface` 블록 deprecated → `primary_network_interface` + `aws_network_interface_attachment`
- **기만 관점 수정**: 디코이 SG 이름 `moayeyak-decoy-sg` → `moayeyak-db-backup-sg`(IMDS `meta-data/security-groups`로 디코이 안에서 보였음), `instance_metadata_tags = disabled`, IMDS hop 2(세 서버 같게), `ignore_changes = [ami]`(서버 교체 방지)
- 검증: fmt·validate, **`terraform test` mock 6개**(팜 중첩/metal, 투영 ENI, 개수·구간 검증, 웹훅) — 테스트가 metal 이름 판정 버그(`m7i.metal-24xl`) 발견·수정. static.sh에 ⑥ Terraform 검사 + ②-3 **AWS 리소스 이름·설명 용어 검사**(변이 시험으로 확인)
- **plan 못 함**: 로컬 AWS 자격증명 무효(`InvalidClientTokenId`) → 11/28 자격증명 다시 설정 후 plan
- 투영 주소 두 단계(README): 서버만 apply → engine plan(블렌딩이 주소 결정) → tfvars `projections` → 다시 apply → aws.yml sensor_nics
- **사용자 결정 대기**: CloudTrail·EventBridge 단일 리전(CLAUDE.md) → 다른 리전·STS 전역 엔드포인트(us-east-1 기록)로 키를 쓰면 경보 없음. 다중 리전 추적 + us-east-1 규칙으로 막을지
- 한계 기록: S3 객체 시각·IAM 생성일 못 되돌림(서사 2025-09), OS hostname은 SSM 쪽

- **11/28 세션이 바로 할 일(순서)**: 서울 리전 C8i/M8i/R8i 중첩 or metal 콘솔 확인 → Terraform 완성·apply(4절 9번) → aws.yml 값 채움(Terraform 출력) → 미끼 레지스트리 S3·Ansible aws_ssm(4절 8번) → backup-legacy 실제 IAM 키(권한 없음) → 전 역할 공격자 시점·경로·안쪽·탐지 검사 + compare.py 역할 규칙으로 진정성 재측정(4절 6번) → 시나리오1 EC2 리허설. Terraform은 AWS 자격증명이 있어야 apply·검증 가능해 11/28에 함(지금 로컬에선 blind 작성뿐)
