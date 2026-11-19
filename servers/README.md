# servers — 서버에 올라가는 것

| 폴더 | web-01 | app-01 | db-backup-01 |
|---|---|---|---|
| `base/` 공통(한 벌, 변경 A) | ✓ | ✓ | ✓ |
| `hosts/<호스트>/` 역할 | — | PostgreSQL, 백업 cron | sshd(IP별), rsync, `backup` 계정, 옛 덤프, DB 5432 |
| `webapp/` (`deploy/` 포함) | 앱, nginx, systemd | — | — |
| `baits/` 미끼 | T1~T5, T7 | T6 | — |

- 세 서버는 같은 베이스에서 출발하고 **차이는 역할에서만** 둔다(`docs/02-infra-design.md` 2절). 공통 설정을 `hosts/`에 복사하지 않는다(사본이 어긋나면 디코이 전용 흔적)
- web-01 역할은 회사 코드의 일부라 `hosts/`가 아니라 `webapp/deploy/`에 둔다
