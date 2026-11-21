provider "aws" {
  region = var.region

  # 모든 리소스에 공통 태그 자동 부착
  default_tags {
    tags = var.tags
  }
}

# Ubuntu 24.04 LTS(amd64, gp3) AMI — Canonical 공개 SSM 파라미터로 리전 자동 매칭
data "aws_ssm_parameter" "ubuntu_2404" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

# 네트워크: VPC·서브넷 2개·IGW·라우트·S3 게이트웨이 엔드포인트
module "network" {
  source = "./modules/network"

  project              = var.project
  vpc_cidr             = var.vpc_cidr
  public_subnet_cidr   = var.public_subnet_cidr
  internal_subnet_cidr = var.internal_subnet_cidr
  availability_zone    = var.availability_zone
}

# 세 서버 공통 SSM/CloudWatch 인스턴스 프로파일
module "ssm_role" {
  source  = "./modules/ssm-role"
  project = var.project
}

# 보안 그룹 3개
module "security" {
  source = "./modules/security"

  project  = var.project
  vpc_id   = module.network.vpc_id
  vpc_cidr = module.network.vpc_cidr
  admin_ip = var.admin_ip
}

# ---------------------------------------------------------------- 호스트 3대
# web-01 — 모아예약 웹(public, 의도적 취약점 → 초기 침투 지점)
module "web_01" {
  source = "./modules/host"
  # EIP 는 IGW 가 VPC 에 붙은 뒤에만 연결된다. EIP→ENI→서브넷 경로엔 IGW 가 없어 순서를 강제
  depends_on = [module.network]

  project              = var.project
  name                 = "web-01"
  ami_id               = data.aws_ssm_parameter.ubuntu_2404.value
  instance_type        = "t3.small" # 11/21: 1GiB에선 ClamAV 정기 검사(세 서버 공통 cron)가 OOM
  subnet_id            = module.network.public_subnet_id
  security_group_id    = module.security.web_sg_id
  iam_instance_profile = module.ssm_role.instance_profile_name
}

# app-01 — 운영 PostgreSQL + S3 백업(internal)
module "app_01" {
  source = "./modules/host"
  # EIP 는 IGW 가 VPC 에 붙은 뒤에만 연결된다. EIP→ENI→서브넷 경로엔 IGW 가 없어 순서를 강제
  depends_on = [module.network]

  project              = var.project
  name                 = "app-01"
  ami_id               = data.aws_ssm_parameter.ubuntu_2404.value
  instance_type        = "t3.small" # 11/21: 1GiB에선 ClamAV 정기 검사(세 서버 공통 cron)가 OOM
  subnet_id            = module.network.internal_subnet_id
  security_group_id    = module.security.app_sg_id
  iam_instance_profile = module.ssm_role.instance_profile_name
}

# db-backup-01 — 디코이(internal, 단일 호스트 다중 주소: 보조 사설 IP 3개)
module "db_backup_01" {
  source = "./modules/host"
  # EIP 는 IGW 가 VPC 에 붙은 뒤에만 연결된다. EIP→ENI→서브넷 경로엔 IGW 가 없어 순서를 강제
  depends_on = [module.network]

  project              = var.project
  name                 = "db-backup-01"
  ami_id               = data.aws_ssm_parameter.ubuntu_2404.value
  instance_type        = "t3.small"
  subnet_id            = module.network.internal_subnet_id
  security_group_id    = module.security.decoy_sg_id
  iam_instance_profile = module.ssm_role.instance_profile_name
  secondary_ip_count   = 3
}

# 11/28: modules/storage(S3 버킷), modules/iam-backup(backup-writer·backup-legacy), modules/cloudtrail
