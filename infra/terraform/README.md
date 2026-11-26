# infra/terraform — AWS 인프라 프로비저닝 (Deceptive-2)

`docs/02-infra-design.md` 설계 + 11/22~23 변경(투영 센서·팜, KVM 디코이 VM)을 코드로 올린다.
**인프라 프로비저닝만** 담당하고, OS 설정·미끼·함정·디코이 VM은 범위 밖(SSM + 미끼 엔진 `baits/engine.py`, 변경 C).

## 상태
- 11/21: 첫 뼈대(VPC·서브넷 2개·SG 3개·호스트 3대), Terraform 1.17.2 + AWS provider 5.100.0, `validate` 통과
- **11/26: 지금 설계로 다시 씀** — farm 서브넷, sensor(+투영 ENI), farm(중첩 가상화), EDH 트랩 포트, backup-writer·backup-legacy, 백업·운영 버킷, CloudTrail + EventBridge(읽기 전용 호출 포함). provider **6.74.0**(중첩 가상화 옵션이 6.x에만 있음 — 스키마로 확인), random 3.9.1. `fmt -check`·`validate` 통과
- **apply·plan 전**: AWS 자격증명이 무효였음(11/26 `InvalidClientTokenId`) → 11/28에 자격증명 다시 설정 후 `plan`
- state: **로컬**(백엔드 없음), `*.tfstate`·`terraform.tfvars`는 `.gitignore`

## 구성
```
versions.tf              provider/TF 버전 핀(aws ~> 6.74, random ~> 3.6)
variables.tf             리전·CIDR·admin_ip·AMI 고정·팜 타입·EDH 트랩 포트·투영 주소·웹훅
main.tf                  provider + 모듈 조립(서버 5대)
outputs.tf               aws.yml 채울 값(인스턴스 ID·사설 IP·팜 터널 끝·투영 ENI·AMI serial·버킷)
modules/
  network/      VPC·서브넷 3개(public·internal·farm)·IGW·라우트·S3 게이트웨이 엔드포인트
  security/     SG: web·app·db-backup(회사 서버) + relay(센서 관리)·relay-in(투영 ENI)·farm + EDH 트랩 포트
  ssm-role/     공통 SSM·CloudWatch 인스턴스 프로파일
  host/         ENI·EIP·인스턴스 1대(서버 5대가 같은 모듈 — 같은 모양)
  projection/   투영 ENI(디코이마다 하나, 주 IP = 투영 주소) + 센서에 붙이기
  storage/      moayeyak-db-backup-<난수6>(30일 만료)·moayeyak-ops-<난수6>(버전 관리)
  iam-backup/   backup-writer 역할(app-01) · backup-legacy 사용자(권한 0, 키 없음)
  cloudtrail/   단일 리전 추적(읽기+쓰기) → EventBridge(backup-legacy 호출 전부) → 웹훅(선택)
```

| 호스트 | 서브넷 | 타입 | SG | 프로파일 |
|---|---|---|---|---|
| web-01 | public | t3.small | web(80/443 ← 내 IP, 8080 ← VPC) | ssm |
| app-01 | internal | t3.small | app(22·5432·6379 ← VPC) | **backup-writer** |
| db-backup-01 | internal | t3.small | db-backup(전체 ← VPC) | ssm |
| sensor | internal(관리) + 투영 ENI | t3.small | relay(인바운드 없음) / relay-in(전체 ← VPC) | ssm |
| farm | farm | m8i.large(중첩) 또는 *.metal | farm(UDP 51820 ← sensor, 51821~ ← web·app) | ssm |

## 설계 메모 — 왜 이렇게
- **NAT 금지** → internal·farm 서브넷도 `0.0.0.0/0 → IGW` + EIP로 아웃바운드. 외부 유입 차단은 **보안 그룹 인바운드**로만
- **서버 안에서 보이는 이름**(IMDS): 보안 그룹 이름(`meta-data/security-groups`), 인스턴스 프로파일·역할 이름(`iam/info`). 그래서 디코이 SG를 `moayeyak-decoy-sg` → **`moayeyak-db-backup-sg`**(11/26 — 예전 이름은 디코이 안에서 curl 한 번에 "decoy"를 보여 줬음). 인스턴스 태그는 `instance_metadata_tags = disabled`로 IMDS에 안 보이게
- **세 회사 서버는 같은 모양**: 같은 AMI·타입·IMDS 설정(토큰 필수, hop 2 = Ubuntu 24.04 AMI 기본)·디스크·user_data 없음
- **AMI 교체 방지**: `ignore_changes = [ami]` — 새 AMI가 나와도 서버를 다시 만들지 않음(호스트 키·데이터·서사 흔적 소실 방지). 패치는 서버 안 unattended-upgrades
- **투영**: VPC는 주소를 그 주소를 가진 ENI에만 넘김(L2 없음) → 투영 주소 = 센서 투영 ENI의 주 IP. 센서 OS는 그 NIC에서 주소를 안 받고(`dhcp4: false`) relay로 넘김. 디코이마다 ENI 따로(같은 MAC 묶임 방지, HANDOFF 9절)
- **src/dst check 전부 켬**: 센서는 자기 ENI 주소로만 받고 내보내고, EDH는 이중 DNAT 뒤 자기 주소로 응답, 터널은 캡슐화 — 끌 곳 없음(첫날 확인)
- **터널 SG**: 센서·EDH가 `PersistentKeepalive`로 먼저 연결 → 팜만 인바운드
- **비밀값**: `backup-legacy` 액세스 키는 Terraform으로 안 만든다(state에 비밀 키 평문). 웹훅 URL은 `terraform.tfvars`에만(커밋 금지) — 단 state엔 남음

## 투영 주소 두 단계
투영 주소는 미끼 엔진의 블렌딩이 이웃을 보고 고른다(이웃 옆 주소). 그래서:
1. `projections = {}`로 `apply` → 서버 5대(센서는 관리 ENI만)
2. `infra/env/aws.yml` 채움 → `python3 infra/env/render.py aws` → `engine.py collect` → `engine.py plan`(투영 주소 결정)
3. 그 주소를 `terraform.tfvars`의 `projections`에 넣고 다시 `apply` → 투영 ENI가 센서에 붙음(인스턴스 재생성 없음)
4. `output projection_enis`의 NIC 이름(첫날 센서에서 MAC으로 확인)을 aws.yml `segments.<구간>.sensor_nics`에 → render → `engine.py apply`

## 알려진 한계
- **CloudTrail·EventBridge가 서울 리전 하나**(CLAUDE.md 단일 리전): 공격자가 다른 리전(또는 STS 전역 엔드포인트 → us-east-1 기록)으로 키를 쓰면 규칙에 안 옴 — 사용자 결정 대기
- **S3 객체 시각은 못 되돌림**: 백업 버킷은 서사상 2025-09부터지만 객체는 구축 날부터. 30일 만료로 구축 30일 뒤엔 "오래된 버킷의 최근 30일"과 같은 모양
- **IAM 생성일**(backup-legacy)도 못 되돌림 — 권한 0이라 공격자는 `iam:GetUser`로 못 봄
- OS hostname(결정: 역할 이름 그대로)은 Terraform이 아니라 OS 쪽(SSM, 공통 베이스)에서 — EC2 기본은 `ip-10-0-x-x`

## 쓰는 법
```sh
cp terraform.tfvars.example terraform.tfvars   # admin_ip(curl -s https://checkip.amazonaws.com), 필요하면 alert_webhook_url
terraform init
terraform fmt -check -recursive && terraform validate
terraform plan        # -/+ (교체)가 서버에 나오면 멈추고 확인
terraform apply
terraform output -json
aws iam create-access-key --user-name backup-legacy   # T6 미끼 키(출력은 저장소·state에 두지 않고 엔진이 주입)
# 정리: terraform destroy (trail 버킷은 force_destroy — 필요한 로그는 먼저 내려받기)
```
