# 시중 디셉션 솔루션 조사 — 디셉션의 핵심 문제와 벤더별 해법

작성: 2026-11-19 · 개정: 2026-11-19 (벤더 나열 → "디셉션이 풀어야 하는 문제" 기준 교차 분석. 근거는 특허·제3자 기술 리뷰·공식 문서)

> 읽는 법: 2절이 본론. 디셉션 제품이 공통으로 풀어야 하는 문제 6개를 세우고, 벤더가 각각 어떻게 풀었는지, 그 선택이 무엇을 대가로 치렀는지, 원청 내부 보안팀과 내 프로젝트에 무엇을 의미하는지를 본다. 3절은 근거가 된 벤더별 동작 사실. 근거 표시: [공식] [특허] [리뷰] [사례]

## 1. 조사 대상
| 제품 | 계보 | 구조 요약 |
|---|---|---|
| Proofpoint Shadow | Illusive Networks | 관리 서버가 엔드포인트에 미끼를 원격 배포(에이전트 없음), 미끼의 목적지는 트랩 서버·AD |
| SentinelOne Identity + Hologram | Attivo (BOTsink·ThreatStrike·ADSecure) | 실제 OS·골든 이미지 디코이 + 엔드포인트 미끼 + AD 응답 조작·연결 전환, Identity는 현재 S1 에이전트 일부 |
| Zscaler Deception | Smokescreen IllusionBLACK | 에뮬레이션 앱 대량 디코이 + 일부 완전 상호작용(RDP) + ZTNA 에이전트로 미끼 배포·자동 격리 |
| Acalvio ShadowPlex | — | 중앙 디셉션 팜 + VLAN별 경량 센서 터널로 디코이 투영, AI 블렌딩 |
| Thinkst Canary | — | 저상호작용 트립와이어 장비·토큰 (비교 기준점으로만 사용) |

## 2. 디셉션의 핵심 문제 6개와 벤더별 해법

### 문제 1. 미끼를 "어떤 경로로" 실제 환경에 깔 것인가 (배포 채널)
| 벤더 | 해법 | 근거 |
|---|---|---|
| Illusive | 관리 서버가 엔드포인트 맥락(로그인 사용자, 실행 프로세스)을 읽고 기계별 미끼를 골라 원격 설치. 상주 에이전트 없음 | [특허] US10382483, [리뷰] KuppingerCole |
| Zscaler | 이미 깔려 있는 ZTNA 에이전트(Client Connector)가 미끼를 심음 | [해설] |
| SentinelOne | 이미 깔려 있는 EDR 에이전트의 Identity 모듈 | [공식] |
| Acalvio | AI 추천 엔진이 브레드크럼 내용·배치를 제안, 관리 콘솔에서 사이트·서브넷별 배포 | [공식][리뷰] |

**분석**
- 셋 중 둘(Zscaler, SentinelOne)은 디셉션을 위해 새 경로를 만들지 않고 **이미 고객이 운영하는 제어 평면(ZTNA·EDR 에이전트)에 얹었다.** Illusive는 에이전트 없이 원격 관리 접근으로 같은 효과를 낸다
- 즉 기업 환경에서 디셉션의 진짜 비용은 미끼를 만드는 것이 아니라 **수천 대에 깔고 유지하는 경로**다. 벤더 경쟁력이 미끼 종류보다 배포 채널에서 갈림
- **원청 시사점**: 디셉션을 도입할지는 "이미 가진 배포 채널(MDM, 구성 관리, EDR)에 얹을 수 있는가"로 판단해야 한다
- **내 프로젝트**: 미끼를 손으로 심지 말고 SSM(Run Command/State Manager) 또는 Ansible로 배포 → "이미 쓰는 관리 채널에 얹는다"를 그대로 재현. 미끼 교체·회수도 같은 채널로

### 문제 2. 디코이를 진짜처럼 보이게 하면서 개수를 늘리는 법 (진정성 × 규모 × 비용)
| 벤더 | 해법 | 포기한 것 |
|---|---|---|
| Attivo | 실제 OS + 고객 골든 이미지 디코이, 네트워크에 투영 | 디코이당 자원 비용 |
| Smokescreen/Zscaler | 수백 종 내장 앱 에뮬레이션으로 대량 생성(MirageMaker), 깊이가 필요한 곳만 완전 상호작용 OS(RDP) | 에뮬레이션 디코이의 깊은 관여 시 일관성 |
| Acalvio | 중앙 팜에 디셉션을 두고 VLAN별 센서 터널로 그 구간 주소를 할당해 투영, AI가 주변 이름·서비스와 섞이게 속성 생성 | 터널 경유에 따른 네트워크 흔적 가능성(공개 측정 없음 — 추정), 블렌딩 품질 비공개 |
| Illusive | 디코이 서버보다 실제 엔드포인트 위 미끼를 주력, 고상호작용 VM은 별도 모듈(골든 이미지) | 미끼가 실제 단말에 있어 정상 작업과 충돌 위험 |

**분석**
- 진정성·규모·비용 셋을 동시에 만족한 벤더는 없다. 모두 **둘을 고르고 하나를 다른 장치로 보완**한다: Attivo는 진정성+규모를 고르고 비용을 투영으로 줄임, Zscaler는 규모+비용을 고르고 진정성은 선택적 실제 OS로 보완, Acalvio는 규모+비용을 고르고 진정성을 AI 블렌딩에 맡김
- 공통적으로 **"넓이(많은 디코이)"와 "깊이(실제 OS)"를 분리**한다. 하나의 디코이로 둘 다 하려 하지 않는다
- 투영의 실체(Acalvio 특허): OS 하나에 IP 여러 개가 아니라, **서로 다른 디셉션 여러 개를 중앙에 두고 네트워크 존재만 각 구간으로 옮김**
- **내 프로젝트**: 내 "디코이 투영"은 원리가 다르다(OS 하나에 IP 여러 개) → **단일 호스트 다중 주소(넓이용, 포트·배너만)**와 **실제 OS 디코이(깊이용)**로 역할을 명시적으로 나누고, 로그인 후 페르소나가 같아지는 한계를 "벤더가 중앙 팜을 택한 이유"로 정리

### 문제 3. 감시를 공격자에게 들키지 않고, 끌 수도 없게 하는 법
| 벤더 | 해법 |
|---|---|
| Illusive | 엔드포인트엔 감시를 두지 않고 **미끼의 목적지(트랩 서버, AD 로그인 실패)에서 탐지** [리뷰]. 고상호작용 디코이 안의 감시는 **난독화된 루트킷으로 은닉** [리뷰] |
| Acalvio | 디셉션 자체가 중앙 팜에 있음 → 감시도 팜 쪽. 엔드포인트 에이전트리스 [공식] |
| SentinelOne · Zscaler | 감시를 **원래 깔려 있는 EDR·ZTNA 에이전트**에 둠 |

**분석 — 가장 중요한 발견**
- 언뜻 SentinelOne·Zscaler는 "에이전트가 보이는" 약점을 가진 것 같지만, 그 에이전트는 **회사의 모든 정상 단말에도 똑같이 깔려 있다.** 공격자 입장에서 EDR 에이전트는 이상 신호가 아니라 정상 환경의 일부다
- 즉 감시 장치가 단서가 되는 조건은 "감시 장치가 있다"가 아니라 **"디코이에만 있고 실제 서버엔 없다(또는 다르다)"**이다
- 이 관점에서 해법은 둘로 정리된다: (a) 감시를 디코이 밖(목적지·팜)으로 뺀다 — Illusive·Acalvio, (b) 감시의 겉모습을 운영 환경과 똑같이 맞춘다 — S1·Zscaler(이미 있는 에이전트 재사용), Illusive AIS(디코이에만 있는 감시는 루트킷으로 숨김)
- **내 프로젝트 — 설계 수정 필요**: 현재 성공 기준 "감시 장치 노출 단서 0개"는 잘못된 목표. 실제 회사 서버에도 CloudWatch 에이전트·auditd는 흔히 깔림 → 목표는 **"디코이의 감시 흔적이 운영 서버(app-01)와 동일"**이어야 한다. 디코이에만 있는 것(미끼 계정 전용 auditd 규칙, 5432를 연 Python 프로세스)만 구별 단서로 센다
  - 구현: app-01과 디코이에 **같은 에이전트·같은 기본 auditd 규칙 세트**를 깔고, 디코이 전용 규칙은 최소화
  - 남는 디코이 전용 흔적(더미 DB 리스너)은 목적지 탐지의 대가로 기록

### 문제 4. 미끼가 실제 환경에 있을 때 오탐을 어떻게 막는가
| 벤더 | 해법 |
|---|---|
| Illusive | 기계별 맥락에 맞춘 미끼, 정책 기반 배포, 환경이 바뀌면 미끼도 갱신 [특허][리뷰] |
| Zscaler | 디코이를 "정상 사용자는 존재를 모르는 곳"에만 두고, 경보를 **확정 위협으로 간주해 자동 격리** [공식] |
| Acalvio | AI가 다수 경보를 자동 분류해 고신뢰 경보만 생성 [공식] |
| SentinelOne | AD 조회 결과를 숨기거나 가짜로 줄 때 공격자로 판단된 조회에만 적용(판단 방식은 공개 자료로 확인 못 함) |

**분석**
- Zscaler의 "경보 = 확정 위협 → 자동 격리"는 **오탐률이 사실상 0일 때만** 성립한다. 자동 대응의 수준은 오탐률이 결정한다
- 따라서 오탐 튜닝은 품질 개선이 아니라 **어떤 미끼에 자동 대응을 걸 수 있는지를 결정하는 관문**
- **내 프로젝트 — 설계 연결**: 차단 모드(여유 시)를 켜는 조건을 "기준선에서 오탐 0건이었던 미끼 유형에만"으로 명시. 오탐 분석표에 미끼 유형별 열을 두고, 유형별로 "자동 차단 가능 / 경보만"을 판정 → 오탐 튜닝과 대응 모드가 하나의 논리로 이어짐

### 문제 5. 경보가 울린 뒤 무엇을 얻을 것인가 (탐지 후 가치)
| 벤더 | 해법 |
|---|---|
| Illusive | 트랩 서버가 응답을 일부러 늦추는(tar-pit) 동안 관리 서버가 **공격자가 출발한 실제 엔드포인트에 포렌식 도구를 즉석 투입** [특허] |
| Attivo/Hologram | 디코이 안에서 공격자 행동 전체를 기록, 가짜 데이터 제공, 위협 정보 수집 [공식] |
| Zscaler | 침해된 사용자의 실제 앱 접근을 즉시 차단 [공식] |

**분석**
- Illusive가 포렌식을 **디코이가 아니라 출발 엔드포인트**에서 한다는 점이 핵심. 원청 대응자에게 가장 급한 정보는 "공격자가 디코이에서 뭘 했나"보다 **"어느 실제 서버가 뚫렸고 거기에 무엇이 남았나"**다
- Attivo식 관찰은 위협 정보(공격자 도구·기법)에 강하고, Illusive식은 사고 대응(침해 범위 확정)에 강하다
- **내 프로젝트 — 기능 추가 제안(작음, AWS 네이티브)**: 경보 발생 시 침투 체인 상관분석이 찾아낸 **출발 내부 IP의 인스턴스에 SSM Run Command로 포렌식 스냅샷**(프로세스 목록, 네트워크 연결, 최근 로그인, 최근 변경 파일, 셸 히스토리)을 자동 수집해 경보에 첨부 → Illusive의 "출발지 포렌식"을 직접 구현. 더미 DB 리스너의 응답 지연(tar-pit)은 수집 시간을 버는 장치로 함께 검증(여유 시)

### 문제 6. 디셉션과 실제 노출 제거(위생)의 관계
| 벤더 | 해법 |
|---|---|
| Illusive | Attack Surface Manager로 엔드포인트의 실제 불필요 자격증명·연결을 찾아 제거하는 기능을 디셉션과 함께 제공 [리뷰] |
| Attivo | ADAssessor 등으로 AD 노출 평가 병행 [공식] |

**분석**
- 공격자가 미끼를 고를지 실제 자격증명을 고를지는 경쟁 관계다. **실제 남은 자격증명이 많을수록 미끼가 선택될 확률이 떨어진다** → 그래서 위생과 디셉션을 묶어 판다
- **내 프로젝트**: 내 AWS 미끼 서사("역할 전환 후 남은 장기 키") 자체가 위생 실패 사례. 보고서에서 "원청이라면 먼저 실제 장기 키를 찾아 없애고, 그 자리에 미끼를 둔다"로 정리하고, 진정성 검증과 별개로 **app-01·web-01에 실제로 남은 자격증명이 없는지 점검하는 항목**을 시나리오 전 점검에 추가

## 3. 근거: 벤더별 동작 사실
### Proofpoint Shadow (Illusive)
- 구성: Deception Management Server + 트랩 서버 [리뷰·특허]. 공식 자료는 "에이전트나 악용될 수 있는 허니팟을 쓰지 않는다"고 하지만 구조상 트랩 서버(미끼의 목적지)는 존재 — 정확히는 "엔드포인트에 상주 에이전트가 없다"
- 맥락 기반 맞춤 미끼 배포 [특허 US10382483], 연결 테이블에 트랩 서버가 보이게 하는 미끼 [특허 US10375110], 실제 호스트 포트를 디코이 포트로 쓰고 트랩 서버로 중계 [특허 US10404747]
- 트랩 서버 tar-pit + 출발 엔드포인트 포렌식 투입 [특허 US10382484], 일부 미끼는 AD 로그인 실패로 경보 [리뷰]
- 고상호작용 VM(골든 이미지) + 난독화 루트킷 감시, 실제 노출 제거 모듈 [리뷰]

### SentinelOne (Attivo)
- BOTsink 디코이: 실제 OS·서비스, 운영 골든 이미지 맞춤, 네트워크에 투영 [공식 데이터시트]
- ThreatStrike: 가짜 자격증명, SSH 토큰, 클라우드 키, SMB 공유·매핑 드라이브 [공식]
- ADSecure: AD 조회 결과 은닉·가짜 결과, Deflect: 악성 연결을 디코이로 전환 [공식]
- 미끼 목적지는 블랙홀 IP도 가능하나 디코이가 있으면 현실감 상승 [공식 블로그], Hologram은 환경을 학습해 운영 시스템 옆에 디코이 자동 생성 [공식]

### Zscaler (Smokescreen)
- IllusionBLACK: BSD 기반, 디코이용 보안 하이퍼바이저 [리뷰], MirageMaker로 수백 종 내장 앱 디코이 대량 생성 [리뷰], 서브넷마다 디코이·AD 통합·엔드포인트 미끼 [공식], 디코이 직원(전화·이메일) [리뷰]
- 현재: ZTNA 에이전트가 미끼 배포, RDP 완전 상호작용 디코이 [해설], 경보를 확정 위협으로 보고 자동 격리 [공식]

### Acalvio
- 특허 "Tunneling for Network Deceptions": 투영 지점을 터널 한쪽 끝, 반대쪽은 디셉션 센터. 디셉션에 그 네트워크 주소를 할당해 노드처럼 보이게 [특허·공식]
- 팜에 에뮬레이션·물리 장치 혼재, 터널별 맥락 유지 [특허], 즉석 생성·상호작용 수준 조절 [리뷰], AI 블렌딩(호스트명·사용자명·서비스·브레드크럼) [리뷰·공식], 에이전트리스 [공식]

### Thinkst Canary (비교 기준점)
- 저상호작용 트립와이어. AWS 키 토큰은 Thinkst 소유 계정 CloudTrail 경유, 공식 문서상 2~30분 지연 [공식] — 내 AWS 키 5분 목표의 현실성 근거로만 사용
- 공개 토큰은 TruffleHog가 계정 ID로 판별 [사례] — 내 계정으로 직접 만드는 근거

## 4. 이 분석이 내 설계에 요구하는 변경 (제안 — 확정 전)
| # | 변경 | 근거 문제 | 일정 영향 |
|---|---|---|---|
| A | 성공 기준 "감시 장치 노출 0개" → **"디코이의 감시 흔적이 운영 서버와 동일, 디코이 전용 흔적만 구별 단서로 셈"**. app-01과 디코이에 같은 에이전트·기본 규칙 세트 | 문제 3 | 없음(11/22 구성 시 함께) |
| B | "디코이 투영" → **"단일 호스트 다중 주소(넓이)" + "실제 OS 디코이(깊이)"**로 명칭·역할 분리 | 문제 2 | 없음 |
| C | 미끼 배포를 **SSM/Ansible**로(손 배포 금지), 회수·교체도 같은 채널 | 문제 1 | 11/26 소폭 |
| D | 오탐 분석표에 **미끼 유형별 자동 차단 가능 여부** 판정, 차단 모드는 오탐 0 유형에만 | 문제 4 | 없음(12/1 분석 시) |
| E | 경보 시 **출발 인스턴스에 SSM Run Command 포렌식 스냅샷** 자동 수집·첨부 | 문제 5 | 11/29 반나절 — 대신 HASSH(여유 시) 삭제 |
| F | 시나리오 전 **실제 남은 자격증명 점검** 항목 | 문제 6 | 12/2 30분 |

## 5. 기능 단위 대응 (구현 체크용)
| 벤더 기능 | 내 구현 | 범위 |
|---|---|---|
| 실제 OS·골든 이미지 디코이 (Attivo, Illusive AIS, Zscaler RDP) | **기능 1** 실제 OS 디코이 (깊이) | 포함 |
| 중앙 팜 + 터널 투영 (Acalvio) / 에뮬레이션 대량 디코이 (MirageMaker) | **기능 1** 단일 호스트 다중 주소 — 포트·배너 분리 (넓이, 원리가 다름을 명시) | 포함 (3시간 상한) |
| 자동 블렌딩 (Acalvio, Hologram) | **기능 1** 진정성 검증 세트 — 구별 단서 측정과 수동 보완 | 포함 — 차별점 |
| 맥락 기반 엔드포인트 미끼 (Illusive, ThreatStrike, Zscaler) | **기능 2** `.env`·`~/.ssh/config`·`~/.bash_history`·DB 접속 정보, SSM/Ansible 배포 | 포함 |
| 자격증명 저장소 미끼 (Illusive, ThreatStrike, S1 Identity) | **기능 2** `ssh-agent` 미끼 키, 프로세스 환경변수 미끼 | 포함 |
| 목적지 탐지·트랩 서버 (Illusive) | **기능 2** 더미 DB 리스너, **기능 1** 디코이 로그인 경보 | 포함 |
| 클라우드 허니토큰 (Canary, Acalvio) | **기능 2** 장기 키 `backup-legacy`, 내 계정 CloudTrail → EventBridge → Lambda → 웹훅 | 포함 |
| 결과 기반 감시 | **기능 3** P0: authorized_keys·ld.so.preload·cron.d | 포함 |
| 디코이 행동 기록 (Attivo, IllusionBLACK) | **기능 4** 디코이 세션 명령 첨부, 판별·정찰 명령 표시 | 포함 |
| 출발지 포렌식 (Illusive) | **제안 E** SSM Run Command 포렌식 스냅샷 | 제안 |
| tar-pit (Illusive) | 더미 DB 리스너 응답 지연 | 여유 시 |
| 경보 연동·상관분석 | **기능 4** 웹훅 + CloudWatch Logs, 침투 체인 상관분석 | 포함 |
| 경보 억제 | 오탐 튜닝 — 원인별 억제 규칙, 미끼 유형별 자동 대응 판정(제안 D) | 포함 |
| 자동 격리 (Zscaler) | 차단 모드 — 오탐 0 미끼 유형에만 | 여유 시 |
| AD 응답 조작·연결 전환 (ADSecure, Deflect) | — | 제외 (대비로 언급) |
| AI 자동 배치·동적 생성 (Acalvio) | — | 제외 |
| 노출 제거 (Illusive ASM, Attivo ADAssessor) | **제안 F** 실제 남은 자격증명 점검 | 제안 |

## 6. ATT&CK 커버리지
### 6-1. P0 — 성공 기준 판정 대상 (탐지율 100% 요구)
| 시나리오 | 단계 | ATT&CK | 탐지 기능 |
|---|---|---|---|
| 1 웹 침투→횡적 이동 | 초기 침투 | T1190 | 탐지 대상 아님(전제) |
|  | 자격증명 탐색 | T1552.001, T1552.004 | 기능 2 (미끼 파일 열람 감시 — 호스트 쪽) |
|  | 내부 정찰 | T1018, T1046 | 기능 1 (디코이 포트 접속 — 목적지 쪽) |
|  | 디코이로 SSH 이동 | T1021.004, T1078 | 기능 1·2 (미끼 계정 로그인 — 목적지 쪽) |
|  | 디코이 내 판별·정찰 명령 | T1497.001, T1497.002, T1518.001 | 기능 4 (로그인 경보에 세션 명령 첨부) |
|  | 미끼 DB 계정 사용 | T1078 | 기능 2 (더미 DB 리스너 — 목적지 쪽) |
| 2 남은 장기 AWS 키 | 키 사용 | T1552.001 → T1078.004 | 기능 2 (호스트 1차 + CloudTrail 2차) |
| 3 봇 행동 재현 | SFTP 반입 | T1105 | 기능 3·4 |
|  | 지속성 | T1574.006, T1053.003, T1098.004 | 기능 3 (P0) |

### 6-2. P1 — 구현한 만큼 별도 보고
| 시나리오 | 단계 | ATT&CK | 탐지 기능 |
|---|---|---|---|
| 3 봇 행동 재현 | 실행·숨김 | T1059.004, T1564.001 | 기능 3 |
|  | 지속성(셸 시작 파일) | T1546.004 | 기능 3 |
|  | 자격증명 덤프 | T1003.008 | 기능 3 |
|  | 삭제된 페이로드 증거 | — | 기능 3 (사본 보존) |

## 출처
**Proofpoint Shadow (Illusive)**
- [공식] https://www.proofpoint.com/us/products/identity-threat-detection-response/shadow
- [공식] https://www.proofpoint.com/sites/default/files/solution-briefs/pfpt-au-sb-shadow.pdf
- [리뷰] https://www.scworld.com/product-test/illusive-networks-illusive
- [리뷰] https://www.kuppingercole.com/research/ev80426/illusive-platform
- [특허] US10382483 https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/10382483
- [특허] US10382484 https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/10382484
- [특허] US10375110 https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/10375110
- [특허] US10404747 https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/10404747

**SentinelOne (Attivo)**
- [공식] BOTsink 데이터시트 https://www.asia-net.com.hk/wp-content/uploads/2021/11/Attivo_Networks-Botsink-Family.pdf
- [공식] Attivo 포트폴리오 https://assets.applytosupply.digitalmarketplace.service.gov.uk/g-cloud-13/documents/700039/960932579304887-service-definition-document-2022-05-13-1543.pdf
- [공식] Attivo 디셉션 백서 https://www.mtechpro.com/marketing/newsletter/2019/oct/dyncontent/Attivo_Networks_Understanding_Deception_technology_FINAL_9112019.pdf
- [공식] https://fr.sentinelone.com/?p=1639
- [공식] https://www.sentinelone.com/blog/exit-sandman-how-sentinelone-deflects-apt-level-identity-security-risks/

**Zscaler (Smokescreen)**
- [공식] https://www.zscaler.com/products/deception
- [공식] https://www.zscaler.com/blogs/product-insights/introducing-integrated-deception-part-world-s-first-and-only-next-gen-ztna
- [리뷰] https://www.scworld.com/news/smokescreen-illusionblack
- [리뷰] https://www.scworld.com/product-test/smokescreen-technologies-illusionblack-3-7
- [공식] https://www.smokescreen.io/lateral-movement-detection/
- [해설] https://www.securityscientist.net/blog/12-questions-and-answers-about-zscaler-deception/

**Acalvio**
- [공식] https://www.acalvio.com/blog/cyber-deception/tunneling-for-network-deceptions/
- [특허] https://patents.google.com/patent/WO2017189765A1/en
- [리뷰] https://www.scworld.com/news/acalvio-technologies-shadowplex
- [리뷰] https://www.csoonline.com/article/562559/acalvio-weaves-a-web-of-deception-on-demand.html
- [공식] https://www.acalvio.com/?p=2325
- [공식] https://www.acalvio.com/resources/guide/acalvio-cyber-deception-buyers-guide/

**Thinkst Canary**
- [공식] https://docs.canarytokens.org/guide/aws-keys-token.html
- [사례] https://grafana.com/blog/canary-tokens-learn-all-about-the-unsung-heroes-of-security-at-grafana-labs/

**주의**: 특허는 출원 시점 설계라 현재 제품과 다를 수 있음. 인수 이후 구조 변화 가능(특히 SentinelOne Identity는 현재 에이전트 기반)
