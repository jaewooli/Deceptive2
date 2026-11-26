provider "aws" {
  region = var.region

  # 모든 리소스에 공통 태그 자동 부착(인스턴스 태그는 IMDS에 안 보이게 꺼 둠 — host 모듈)
  default_tags {
    tags = var.tags
  }
}

# Ubuntu 24.04 LTS(amd64, gp3) AMI — Canonical 공개 SSM 파라미터. var.ami_id가 있으면 그것으로 고정.
data "aws_ssm_parameter" "ubuntu_2404" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

locals {
  ami_id = coalesce(var.ami_id, data.aws_ssm_parameter.ubuntu_2404.insecure_value) # AMI ID는 비밀이 아님(String 파라미터)
  # 팜: metal이면 중첩 옵션 필요 없음(지원도 안 함). metal 이름은 m5.metal·m7i.metal-24xl처럼 뒤에 크기가 붙기도 함(테스트로 발견)
  farm_nested = !strcontains(var.farm_instance_type, ".metal")
}

# AMI 이름 = serial(예: ...-server-20261017). 투영 디코이 VM 이미지를 같은 serial로 받는 근거(aws.yml farm.guest.base_image)
data "aws_ami" "server" {
  owners = ["099720109477"] # Canonical
  filter {
    name   = "image-id"
    values = [local.ami_id]
  }
}

# ---------------------------------------------------------------- 공통
module "network" {
  source = "./modules/network"

  project              = var.project
  vpc_cidr             = var.vpc_cidr
  public_subnet_cidr   = var.public_subnet_cidr
  internal_subnet_cidr = var.internal_subnet_cidr
  farm_subnet_cidr     = var.farm_subnet_cidr
  availability_zone    = var.availability_zone
}

# 공통 SSM/CloudWatch 인스턴스 프로파일(web-01·db-backup-01·sensor·farm). app-01만 backup-writer
module "ssm_role" {
  source  = "./modules/ssm-role"
  project = var.project
}

module "security" {
  source = "./modules/security"

  project         = var.project
  vpc_id          = module.network.vpc_id
  vpc_cidr        = module.network.vpc_cidr
  admin_ip        = var.admin_ip
  edh_decoy_ports = var.edh_decoy_ports
}

module "storage" {
  source  = "./modules/storage"
  project = var.project
}

module "iam_backup" {
  source            = "./modules/iam-backup"
  project           = var.project
  backup_bucket_arn = module.storage.backup_bucket_arn
}

module "cloudtrail" {
  source = "./modules/cloudtrail"

  project        = var.project
  suffix         = module.storage.suffix
  watch_user     = module.iam_backup.backup_legacy_name
  enable_webhook = nonsensitive(var.alert_webhook_url != null) # count에 민감값을 못 쓰므로 "있나/없나"만 꺼냄
  webhook_url    = var.alert_webhook_url
}

# ---------------------------------------------------------------- 회사 서버 3대(같은 모양 — 디코이만 다르면 단서)
# EIP 는 IGW 가 VPC 에 붙은 뒤에만 연결된다. EIP→ENI→서브넷 경로엔 IGW 가 없어 순서를 강제(depends_on)

# web-01 — 모아예약 웹(public, 의도적 취약점 → 초기 침투 지점), EDH(8080 → 팜 트랩)
module "web_01" {
  source     = "./modules/host"
  depends_on = [module.network]

  project              = var.project
  name                 = "web-01"
  ami_id               = local.ami_id
  instance_type        = "t3.small" # 11/21: 1GiB에선 ClamAV 정기 검사(세 서버 공통 cron)가 OOM
  subnet_id            = module.network.public_subnet_id
  security_group_id    = module.security.web_sg_id
  iam_instance_profile = module.ssm_role.instance_profile_name
}

# app-01 — 운영 PostgreSQL + S3 백업(internal, 역할 backup-writer), EDH(6379 → 팜 트랩), T6 미끼 자리
module "app_01" {
  source     = "./modules/host"
  depends_on = [module.network]

  project              = var.project
  name                 = "app-01"
  ami_id               = local.ami_id
  instance_type        = "t3.small"
  subnet_id            = module.network.internal_subnet_id
  security_group_id    = module.security.app_sg_id
  iam_instance_profile = module.iam_backup.backup_writer_profile
}

# db-backup-01 — S3 전환 뒤 정리 안 된 옛 백업 서버(internal, 실제 OS, IP 1개)
module "db_backup_01" {
  source     = "./modules/host"
  depends_on = [module.network]

  project              = var.project
  name                 = "db-backup-01"
  ami_id               = local.ami_id
  instance_type        = "t3.small"
  subnet_id            = module.network.internal_subnet_id
  security_group_id    = module.security.db_backup_sg_id
  iam_instance_profile = module.ssm_role.instance_profile_name
}

# ---------------------------------------------------------------- 투영(Acalvio): 센서 + 팜
# sensor — 관리 ENI(internal, 서비스 없음, SSM) + 투영 ENI(디코이마다 하나, modules/projection)
module "sensor" {
  source     = "./modules/host"
  depends_on = [module.network]

  project              = var.project
  name                 = "sensor"
  ami_id               = local.ami_id
  instance_type        = "t3.small" # ENI 3개(관리 1 + 투영 2), ENI당 IPv4 4개
  subnet_id            = module.network.internal_subnet_id
  security_group_id    = module.security.relay_sg_id
  iam_instance_profile = module.ssm_role.instance_profile_name
}

module "projection" {
  source = "./modules/projection"

  project     = var.project
  instance_id = module.sensor.instance_id
  subnet_ids = {
    public   = module.network.public_subnet_id
    internal = module.network.internal_subnet_id
  }
  security_group_id = module.security.relay_in_sg_id
  projections       = var.projections
}

# farm — 디코이 KVM VM + 트랩 컨테이너 + 터널 끝(farm 서브넷, 회사 망에서 직접 안 보임)
module "farm" {
  source     = "./modules/host"
  depends_on = [module.network]

  project               = var.project
  name                  = "farm"
  ami_id                = local.ami_id
  instance_type         = var.farm_instance_type
  nested_virtualization = local.farm_nested
  root_volume_size      = 40 # 디코이 VM 디스크(guest disk_gb 8 × 2) + 기본 이미지 + pcap(손님당 512MB)
  subnet_id             = module.network.farm_subnet_id
  security_group_id     = module.security.farm_sg_id
  iam_instance_profile  = module.ssm_role.instance_profile_name
}
