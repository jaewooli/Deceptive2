provider "aws" {
  region = var.region

  # 모든 리소스에 공통 태그 자동 부착
  default_tags {
    tags = var.tags
  }
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

# 다음 단계(오늘 계속): modules/ssm-role, modules/security, modules/host ×3
# 11/27 이후: modules/storage(S3 버킷), modules/iam-backup, modules/cloudtrail
