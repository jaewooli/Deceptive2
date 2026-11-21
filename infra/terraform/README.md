# infra/terraform — AWS 인프라 프로비저닝 (Deceptive-2)

`docs/02-infra-design.md` 설계를 코드로 올린다. **인프라 프로비저닝만** 담당하고,
OS 설정·미끼·함정 배포는 범위 밖(SSM Run Command/Ansible, 변경 C).

## 상태
- **apply 보류** — AWS 계정 확인 대기 중(11/21). 코드만 먼저 작성(계정 없이 가능한 준비, WBS 11/21).
- 11/21: Terraform 1.17.2 + AWS provider 5.100.0(`.terraform.lock.hcl` 커밋)으로 `fmt -check`·`validate` 통과. `plan`은 자격증명 필요(AMI SSM 파라미터 조회)
- 11/21: 호스트 모듈 3개에 `depends_on = [module.network]` — EIP는 IGW가 VPC에 붙은 뒤에만 ENI에 연결되는데, EIP→ENI→서브넷→VPC 경로에 IGW가 없어 순서가 보장되지 않았음
- 11/21: web-01·app-01 `t3.micro` → `t3.small`. 세 서버 공통 ClamAV 정기 검사(cron)가 1GiB에서 OOM(`../loadtest/README.md`). 세 대가 같은 타입이 되어 인스턴스 타입(IMDS로 보임)도 디코이만의 차이가 아니게 됨
- state: **로컬**(S3/DynamoDB 백엔드 없음 → 추가 비용 0). `*.tfstate` 는 `.gitignore`(계정 ID·리소스 ID·미끼 키 포함 가능).

## 구성
```
versions.tf              provider/TF 버전 핀
variables.tf             region·CIDR·admin_ip·tags
main.tf                  provider + 모듈 조립
outputs.tf               vpc/subnet id
terraform.tfvars.example admin_ip 예시 (실제값은 terraform.tfvars, gitignore)
modules/
  network/               VPC·서브넷 2개·IGW·라우트·S3 게이트웨이 엔드포인트
  ssm-role/              SSM·CloudWatch 인스턴스 프로파일
  security/              보안 그룹 3개
  host/                  ENI(보조 IP)·EIP·인스턴스 — 3번 호출
  # (11/27) storage, iam-backup, cloudtrail
```

`host` 모듈 하나를 web-01/app-01/db-backup-01 3번 호출할 예정(차이는 서브넷·타입·SG·보조 IP 개수 파라미터).

## 설계 메모
- **NAT 금지** → internal 서브넷도 `0.0.0.0/0 → IGW` + 공인 IP 로 아웃바운드. 외부 유입 차단은 **보안 그룹 인바운드**로만(라우팅 아님). 상세는 `modules/network/main.tf` 주석.
- cloud-init 커스텀 user_data 안 씀 — 공통 베이스·미끼까지 전부 SSM/Ansible 한 채널(세 서버 동일성·멱등성·기만 흔적 최소).

## 쓰는 법 (계정 확인 후)
```sh
cp terraform.tfvars.example terraform.tfvars   # admin_ip 채우기 (curl -s https://checkip.amazonaws.com)
terraform init
terraform fmt -check && terraform validate
terraform plan
terraform apply
# 정리: terraform destroy
```
