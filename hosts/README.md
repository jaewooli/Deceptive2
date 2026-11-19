# hosts — 호스트별 역할 구성

세 서버는 같은 베이스(`base/`)에서 출발하고 **차이는 역할에서만** 둔다(`docs/02-infra-design.md` 2절).
여기에는 역할 구성만 둔다. 공통 설정을 여기에 복사하지 않는다(변경 A: 사본이 어긋나면 디코이 전용 흔적이 됨).

- web-01 역할은 회사 코드의 일부라 `webapp/deploy/`에 둔다
- 미끼(T1~T7)는 `baits/`, 탐지 규칙은 `detection/`에 둔다

서버에 올라가는 것 = `base/` + `hosts/` + `webapp/` + `baits/` (+ `detection/`의 호스트 쪽 규칙)
