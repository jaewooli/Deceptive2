# validation — 진정성 검증 세트

"디코이를 실제 운영 서버와 구별할 수 있는가"를 재는 검사 묶음. 같은 검사를 디코이·app-01에 돌리고 서사 시간표·배포판 기본값과 대조해, 어긋나는 항목(= 구별 단서)을 센다.

- **검사 항목: `checks.md`**(11/21 39개 → 11/22 43개, **자동 층(봇)·사람 층(시멘틱)** 으로 나눔) — 사용 흔적 / 구축 흔적 / 연결 흔적 / 감시 흔적 차이(app-01 대비) / 구현 차이 / 이야기 일관성. 항목마다 판정 방식(= 같아야 함, ⏱ 서사 시간표, ↔ 맞물림)과 출처(ATT&CK, Spotless Sandboxes, Bitter Harvest) 표시
- 감시 흔적 항목에 `servers/base/audit/check.sh` 결과(기대·실제 규칙 수, 건너뛴 규칙) 포함 — 세 서버가 같아야 함(11/20)
- 일정: 11/21(항목 정의), 11/22(스크립트·첫 실행, 로컬 VM — 11/21 재배치로 하루 당김), 11/24(보완 후 재측정), 11/29(EC2 재측정), 12/2(최종 재측정)
- 근거: `docs/plan-wbs.md` 3절 기능 1, 5절 성공 기준(진정성)

## 실행
```sh
D=out/validation/$(date +%F); mkdir -p $D        # 원자료는 out/(커밋 안 함), 요약만 아래에
VM_NAME=lt-decoy VM_SSH_PORT=2231 infra/local-vm/vm.sh ssh 'sudo bash -s' < validation/collect.sh > $D/lt-decoy.txt
validation/probe.sh 127.0.0.1 2231 15431 > $D/lt-decoy.probe.txt     # 바깥 응답(E1·E2), 공격자 시점
VM_NAME=lt-decoy VM_SSH_PORT=2231 validation/botprobe.sh infra/local-vm/vm.sh ssh > $D/lt-decoy.bot.txt   # 봇 검사(S1~S4)
# app-01도 같게(2232/15432) →
python3 -I validation/compare.py $D/lt-decoy.txt $D/lt-app.txt --probe $D/lt-decoy.probe.txt $D/lt-app.probe.txt --bot $D/lt-decoy.bot.txt $D/lt-app.bot.txt > $D/report.md
```
| 파일 | 하는 일 |
|---|---|
| `collect.sh` | 서버 안 원자료(항목별 `### ID` 구역). 읽기 전용, stdin으로 실행해 파일을 남기지 않음 |
| `probe.sh` · `pgprobe.py` | 바깥에서 본 SSH KEXINIT·PG 인증 실패 응답. 로그인 시도 없음(PG는 없는 계정 1회 → 디코이 경보는 정상) |
| `botprobe.sh` | 자동 층 S1~S4 — 직전 프로젝트 봇 명령 재현, 바깥에서 일반 계정 SSH로 |
| `compare.py` | 43개 항목 규칙으로 판정 → 층별 디코이 전용 / 공통 / 못 잰 것 / [로컬] 원인 |

측정 자체가 남기는 흔적(막을 수 없음): SSH 로그인 기록, 로그인 세션 execve(auditd), C5의 postgres 로컬 접속 1회

## 결과
### 11/22 첫 측정(보완 전) — 로컬 VM `lt-decoy`·`lt-app`(11/21 부하 테스트 VM 재사용)
| 구분 | 수 | 항목 |
|---|---|---|
| **디코이 전용 단서** | **17** | 사용 흔적 A2·A3·A9·A10, 연결 흔적 C1·C2·C3·C5·C6, 감시 흔적 D1·D3·D5·D7·D8, 이야기 F1·F3·F6 |
| **공통 단서**(서사를 깨는 단서) | **12** | A1·A4·A5·A6·A7(켠 지 한 달 안), B1~B6(2026-10~11 구축), F2(24.04 출시 > 운영 시작) |
| 디코이 ✓ | 7 | A8, C4, D2·D4·D6(패키지·audit 규칙 41줄·포트 같음), E1·E2(SSH·PG 바깥 응답이 app-01과 바이트 단위로 같음), F4 |
| 못 잰 것 | 2 | E3(11/24 다중 주소 이후), F5(IMDS, 11/29 EC2) |

- 디코이 전용 17개 중 12개(A·C·F)는 **아직 안 만든 사용 흔적**(`backup` 계정·덤프·rsync, 11/24 보완 대상)이라 예상대로
- **감시 흔적 5개(D1·D3·D5·D7·D8)는 예상 밖** — 원인 2개: ① moa-notify(세 서버 공통, 11/20)를 app VM에 설치하지 않음 ② ClamAV 매일 검사 cron을 공통 베이스에 넣은(11/21 19:37) 뒤 app VM에 base를 다시 돌리지 않음. 둘 다 "디코이에만 감시 장치가 있다"로 보임 → 11/24 보완
- B2: base에서 rsyslog를 재시작하게 고쳤어도(11/21) **첫 부팅~base 설치 전 줄은 UTC로 남는다** → EC2에서도 같음
- [로컬] 원인(EC2에서는 안 생김, 개수엔 포함): B1 cloud-init 인스턴스 여러 개(vm.sh가 켤 때마다 instance-id 새로 만듦 → 11/22 고침, 그 결과 SSH 호스트 키도 다시 생김), C4 app-01에 web-01 연결 없음, F4 호스트 이름 `lt-decoy`의 "decoy"가 14개 파일에 퍼짐(이름 빼면 0건)

#### 층으로 나눠 보면 (11/22, S1~S4 추가 후)
| 층 | 항목 | 디코이 전용 단서 | 공통 단서 | 못 잰 것 |
|---|---|---|---|---|
| **자동(봇·스캐너)** | 7 | **0** | **0** | E3 |
| **사람(시멘틱)** | 36 | 17 | 12 | F5 |

- **봇에게는 지금도 구별되지 않는다.** 셸 동작 5종·오류 형식·스크립트 실행·하드웨어·uptime·SSH/PG 응답 모두 app-01과 같음. 실제 OS 디코이를 고른 것(직전 프로젝트: 에뮬레이터는 산술 확장 하나로 판별됨)만으로 자동 층은 끝난다
- 단서 29개는 모두 **사람 층** → 보완도 사람 층 작업. [로컬] S3: CPU 모델·GPU 1개는 QEMU·내 PC 값(EC2에서 재확인)
