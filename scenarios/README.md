# scenarios — 검증 시나리오 · 기준선 정상 작업

침투 시나리오를 로컬에서 **리허설**(회귀 테스트)해 P0 탐지가 다 걸리고 한 침투 체인으로 묶이는지 확인한다.
핵심: **실제 익스플로잇·멀웨어는 쓰지 않는다.** 초기 침투(T1190 웹 RCE)는 커버리지 표에서 "탐지 대상 아님(전제)"이라
재현하지 않고, 탐지가 보는 **관측치**(미끼 열람·디코이 접속·미끼 키 로그인·디코이 세션 명령·지속성 쓰기)만 평범한 명령으로 만든다.

## 시나리오 (01-vendor-feature-map 6절 P0)
- 시나리오 1 (`scenario1.sh`): 웹 침투 → 자격증명 탐색 → 디코이로 횡적 이동 → 미끼 DB 계정. **P0 핵심** — 기능 1·2·4 + 침투 체인
- 시나리오 2 (`scenario2.sh`): `backup-legacy` 장기 AWS 키. 로컬은 호스트 1차(열람)만, CloudTrail 2차는 11/28 AWS
- 시나리오 3 (`scenario3.sh`): 관측된 봇 행동 안전 재현(SFTP 반입 → 실행 → 지속성 → 삭제). engagement + P0 결과 기반 감시

## 실행·판정
```
scenarios/run.sh <1|2|3>
```
- 출발지 포렌식 상관기(`forensics/correlate.py watch`)를 켜고 시나리오를 돌린 뒤, 수신기 경보를 source별로 세어
  기대 탐지가 다 왔는지(○/✗) 판정하고, `forensics/chain.py build`로 침투 체인이 한 공격자로 묶였는지 보여 준다.
- 기대 탐지: 시나리오1 = 감사·포트·sshd·세션·postgresql·터널·포렌식·체인 / 2 = 감사 / 3 = sshd·세션·감사
- 원자료: `out/scenarios/`, `out/chains/`, `out/forensics/`
- 성공 기준(plan-wbs 5절): P0 탐지 단계 경보 100%, 호스트 경보 60초 이내(시간은 `infra/checks/detect.py`가 따로 잼), 시나리오1 체인+포렌식

## 기준선 정상 작업 (시간 압축 방식, 11/29 저녁 실행)
- `baseline/app-01.md`: app-01 정상 작업 목록 A1~A14(근거·예상 오탐) — 11/20
- `baseline/run-app-01.sh [배수]`: 그 목록을 "48시간 상당 횟수 × 배수"로 실행, 작업별 시각을 `out/baseline/`에 기록.
  무거운 작업(A9 clamscan·A10 nmap)은 `BASELINE_HEAVY=1`일 때만(11/22 OOM 주의). 11/30에 "예상 오탐"과 수신기 경보를 비교
- web-01·db-backup-01 목록은 11/29 확정(app-01.md 35줄)

## 안전·한계
- 디코이에 남긴 흔적(authorized_keys·bashrc 미끼 줄, /tmp 반입 파일)은 시나리오 끝에 되돌린다 — 디코이를 깨지 않는다
- ld.so.preload/cron.d 같은 루트 지속성은 디코이 backup 계정이 못 써서 시도만 engagement에 기록됨. 그 경로의 **쓰기 탐지**는
  `infra/checks/detect.py`가 진짜 서버에서 검증(안전한 생성·삭제, 이미 있으면 안 건드림)
- 근거: `docs/plan-wbs.md` 5절, 커버리지 `docs/01-vendor-feature-map.md` 6절
