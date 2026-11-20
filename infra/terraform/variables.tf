variable "region" {
  description = "AWS 리전 (서울)"
  type        = string
  default     = "ap-northeast-2"
}

variable "availability_zone" {
  description = "단일 AZ — 3대 모두 같은 AZ(사설망 통신 단순, 비용 절감)"
  type        = string
  default     = "ap-northeast-2a"
}

variable "project" {
  description = "리소스 Name 접두사 겸 식별자"
  type        = string
  default     = "moayeyak"
}

variable "vpc_cidr" {
  description = "VPC CIDR"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidr" {
  description = "public 서브넷 (web-01)"
  type        = string
  default     = "10.0.1.0/24"
}

variable "internal_subnet_cidr" {
  description = "internal 서브넷 (app-01, db-backup-01)"
  type        = string
  default     = "10.0.2.0/24"
}

variable "admin_ip" {
  description = "web-01 80/443 인바운드를 허용할 내 공인 IP를 /32 CIDR 로. terraform.tfvars 로 주입하며 커밋하지 않는다(개인정보). 재시작·ISP 변경 시 갱신."
  type        = string
  # default 없음 — 반드시 terraform.tfvars 로 주입 (security 모듈에서 사용 예정)
}

variable "tags" {
  description = "모든 리소스 공통 태그 (provider default_tags)"
  type        = map(string)
  default = {
    Project   = "moayeyak"
    ManagedBy = "terraform"
  }
}
