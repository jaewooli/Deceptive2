# loadtest — 부하 테스트 (plan-wbs 6절 "11/22 필수 확인")

공통 에이전트 세트 + 역할 서비스 + 기준선 정상 작업(ClamAV 전체 검사)을 동시에 돌려 OOM이 나는지 본다.
**서버에 남기는 코드가 아니다**(`servers/` 밖). `/tmp`에 복사해 실행하고, 끝나면 임시 파일·프로세스를 지운다.

```sh
# 로컬 VM
infra/local-vm/vm.sh ssh 'cat > /tmp/loadtest.sh; sudo bash /tmp/loadtest.sh decoy 300; rm -f /tmp/loadtest.sh' < infra/loadtest/loadtest.sh
# AWS (계정 확인 후): 같은 스크립트를 SSM Run Command(AWS-RunShellScript)로
```

| 프로파일 | 거는 부하 |
|---|---|
| 공통 | 로그인 세션 execve 반복(auditd `50-user-cmd`), `clamscan -r /` |
| `decoy` | sshd 추가 3개(포트 2201~2203, IP별 sshd 대용) + 4개 sshd에 `backup` 공개키 로그인 실패 반복, PG `report_ro`·`sync_svc` 로그인 실패 반복(→ moa-notify 웹훅) |
| `app` | PG 로그인 실패 반복 + `pg_dumpall` 반복 |
| `web` | nginx → gunicorn(워커 2) `/`·`/stores` 동시 요청 |

출력: 에이전트 목록(세 서버 동일 확인용), MemAvailable 유휴·최저, OOM 수(`dmesg`), clamscan 최대 RSS, 최저 시점 상위 RSS.

## 로컬 VM에서 쓰는 것 (VM 전용, 서버 코드 아님)
- CloudWatch 에이전트 `onPremise` 모드는 자격증명이 없으면 `fetch-config`가 실패하고, 서비스는 옛 설정으로 재시작을 반복한다(RSS도 실제와 다름).
  VM에만 AWS 문서 예시 키(가짜 값)로 `/root/.aws/credentials [AmazonCloudWatchAgent]` + `/root/.aws/config [profile AmazonCloudWatchAgent] region`을 두고
  `CWAGENT_MODE=onPremise base/install.sh base`. 에이전트는 실제로 돌고 전송만 `UnrecognizedClientException`으로 거부된다
- web-01 VM은 앱 DB를 SQLite로(실제 web-01에는 PG가 없고 DB는 app-01) — gunicorn 메모리만 잰다
- 로컬엔 보조 IP가 없어 IP별 sshd를 포트로 나눈다. 프로세스 수·메모리는 같다

## 결과 (11/22분, 11/21 로컬 VM · Ubuntu 24.04.5 · 스왑 없음 = EC2 Ubuntu AMI 기본)
| VM | 메모리 | MemAvailable 유휴 → 최저 | OOM | clamscan |
|---|---|---|---|---|
| decoy (t3.small 상당) | 2 GiB | 1545 → 491 MiB | 0 | 최대 RSS 984 MiB, 300초 동안 검사 계속 |
| app (t3.micro 상당) | 1 GiB | 553 → 0 MiB | **1 (clamscan)** | 627 MiB에서 강제 종료 |
| web (t3.micro 상당) | 1 GiB | 326 → 3 MiB | **1 (clamscan)** | 538 MiB에서 강제 종료 |
| app, clamscan만(`/etc`) | 1 GiB | 577 → — | **1** | 574 MiB에서 강제 종료 — 부하가 겹쳐서가 아니라 clamscan 혼자로도 |
| app + 스왑 1GiB(VM에만 임시) | 1 GiB | 581 → 38 MiB | 0 | 600초 안에 안 끝남, 스왑아웃 약 93만 페이지(≈3.6GB) — 쓰래싱 |
| **app (t3.small, 결정 후)** | 2 GiB | 1596 → 452 MiB | 0 | 최대 RSS 1117 MiB |
| **web (t3.small, 결정 후)** | 2 GiB | 1482 → 502 MiB | 0 | 최대 RSS 979 MiB |

- **결정(11/21)**: web-01·app-01을 **t3.small**로(`infra/terraform/main.tf`). 비용 약 +$8.7(약 $23 → 약 $32, Budgets $20 알림은 넘음). 스왑(쓰래싱)·micro만 clamscan 제외(web-01 미끼의 ClamAV 오탐원 측정 불가)·ClamAV 제거 대신

- 에이전트 목록: 세 VM 모두 auditd·SSM 에이전트 snap 3.3.4793.0·CloudWatch 에이전트 1.300075.0b2061-1·freshclam·unattended-upgrades·cron active, `auditctl -l` 41줄
- OOM 때 죽은 것은 clamscan뿐(점수가 가장 높음). PG·gunicorn·에이전트·moa-notify는 살아 있음
- 디코이 웹훅 지연(PG 로그 시각 → 수신): p50 0.2초 / p95 0.4초 / 최대 0.5초. 1분 한도(moa-notify)를 넘는 폭주분은 보류(설계대로)
- 유휴 상위 RSS: CloudWatch 에이전트 약 135~145 MiB(가장 큼), SSM 에이전트 약 16 MiB, snapd 약 45 MiB
