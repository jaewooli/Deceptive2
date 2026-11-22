# servers — 서버에 올라가는 것

| 폴더 | web-01 | app-01 | db-backup-01 |
|---|---|---|---|
| `base/` 공통(한 벌, 변경 A) | ✓ | ✓ | ✓ |
| `hosts/<호스트>/` 역할 | — | PostgreSQL, 백업 cron | sshd, rsync, `backup` 계정, 옛 덤프, DB 5432 |
| `webapp/` (`deploy/` 포함) | 앱, nginx, systemd | — | — |
| `baits/` 미끼 | T1~T5, T7 | T6 | — |
| `detection/` 호스트 쪽 탐지 룰 | ✓ | ✓ | ✓ |

- 세 서버는 같은 베이스에서 출발하고 **차이는 역할에서만** 둔다(`docs/02-infra-design.md` 2절). 공통 설정을 `hosts/`에 복사하지 않는다(사본이 어긋나면 디코이 전용 흔적)
- web-01 역할은 회사 코드의 일부라 `hosts/`가 아니라 `webapp/deploy/`에 둔다
- AWS 쪽 탐지 룰(CloudTrail→EventBridge→Lambda)은 서버에 올라가지 않으므로 루트 `detection/`에 있다. T6은 두 곳에 걸친다

## 투영 (11/22) — 회사 서버가 아닌 것
| 폴더 | 올라가는 곳 | 하는 일 |
|---|---|---|
| `hosts/sensor/` | sensor | 투영 주소로 온 연결을 출발지 그대로 WireGuard로 farm에(정책 라우팅, 서비스 없음) |
| `hosts/farm/` | farm | WireGuard 끝점 + systemd-nspawn 컨테이너 망(컨테이너 veth에 게이트웨이 .1, proxy ARP) |
| `hosts/farm/stg-01/` | farm 안 컨테이너 | 옛 스테이징 디코이 루트파일시스템(`build.sh`)·역할 |
- `base/`(공통 에이전트)는 sensor·farm에도 깐다(AWS 관리·로그). stg-01 컨테이너 안에 무엇이 같고 다른지는 진정성 검증 세트로 잰다
