variable "region" {
  description = "AWS 리전 (서울)"
  type        = string
  default     = "ap-northeast-2"
}

variable "availability_zone" {
  description = "단일 AZ — 모든 서버·ENI가 같은 AZ(센서 ENI는 여러 서브넷에 걸치지만 인스턴스와 같은 AZ여야 붙는다)"
  type        = string
  default     = "ap-northeast-2a"
}

variable "project" {
  description = "리소스 Name 접두사 겸 식별자(회사 이름). 서버 안에서 IMDS로 보이는 이름(보안 그룹 이름)에도 들어가므로 프로젝트 용어 금지"
  type        = string
  default     = "moayeyak"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "public_subnet_cidr" {
  description = "public 서브넷 (web-01, 투영 디코이 public 구간)"
  type        = string
  default     = "10.0.1.0/24"
}

variable "internal_subnet_cidr" {
  description = "internal 서브넷 (app-01, db-backup-01, sensor 관리 ENI, 투영 디코이 internal 구간)"
  type        = string
  default     = "10.0.2.0/24"
}

variable "farm_subnet_cidr" {
  description = "farm 서브넷 (팜 — 회사 망에서 직접 안 보임, 터널만)"
  type        = string
  default     = "10.0.3.0/24"
}

variable "admin_ip" {
  description = "web-01 80/443 인바운드를 허용할 내 공인 IP를 /32 CIDR 로. terraform.tfvars 로 주입하며 커밋하지 않는다(개인정보)."
  type        = string
}

variable "ami_id" {
  description = "서버 AMI 고정값. null이면 Canonical SSM 파라미터의 현재 Ubuntu 24.04를 처음 apply 때 쓰고, 이후엔 바뀌어도 서버를 교체하지 않는다(host 모듈 ignore_changes). 투영 디코이 VM 이미지는 이 AMI와 같은 serial이어야 함(aws.yml farm.guest.base_image)"
  type        = string
  default     = null
}

variable "farm_instance_type" {
  description = "팜 타입. 디코이 VM(KVM)을 돌리므로 중첩 가상화 지원(C8i·M8i·R8i) 또는 metal. .metal이면 중첩 옵션을 끈다(필요 없음). 서울 리전 제공은 apply 전 콘솔/CLI로 확인(HANDOFF 22a)"
  type        = string
  default     = "m8i.large" # 2 vCPU·8 GiB: 디코이 VM 2대(stg 1024MB·dev 896MB) + 트랩 컨테이너 2개 + 팜 OS
}

variable "edh_decoy_ports" {
  description = "회사 서버(EDH)의 안 쓰는 포트 → 팜 트랩(Illusive US10404747). 레지스트리의 active decoy_port 배치와 같아야 한다(engine.py list). VPC 안에서만 연다"
  type        = map(list(number))
  default = {
    "web-01" = [8080]
    "app-01" = [6379]
  }
}

variable "projections" {
  description = <<-EOT
    투영 디코이 = 센서의 투영 ENI 하나(HANDOFF 9절: 디코이 하나 = ENI 하나, 같은 MAC에 묶이면 ARP에서 드러남).
    주소는 엔진의 블렌딩이 고른다(engine.py plan — 이웃 옆 주소). 그 주소를 여기 넣고 apply하면 그 주소를 주 IP로 가진 ENI가 센서에 붙는다.
    처음 apply(서버만) → engine collect·plan → 여기 채움 → 다시 apply → engine apply 순서(README "투영 주소 두 단계").
    t3.small 센서는 ENI 3개(관리 1 + 투영 2)까지.
  EOT
  type = map(object({
    segment      = string # "public" | "internal"
    ip           = string
    device_index = number # 1 또는 2 (0은 관리 ENI). Nitro에서 OS 이름은 보통 ens(5+index) — 첫날 확인
  }))
  default = {}

  validation {
    condition     = length(var.projections) <= 2
    error_message = "t3.small 센서는 ENI 3개(관리 1 + 투영 2)까지. 디코이를 더 투영하려면 센서를 늘린다."
  }
  validation {
    condition     = alltrue([for p in values(var.projections) : contains(["public", "internal"], p.segment) && contains([1, 2], p.device_index)])
    error_message = "segment는 public|internal, device_index는 1|2."
  }
}

variable "alert_webhook_url" {
  description = "backup-legacy 키 사용 경보를 보낼 웹훅(Discord). 비밀값 — terraform.tfvars에만(커밋 금지). state에도 남는다. null이면 EventBridge 규칙만 만들고 대상은 안 붙임"
  type        = string
  default     = null
  sensitive   = true
}

variable "tags" {
  description = "모든 리소스 공통 태그 (provider default_tags). 인스턴스 태그는 IMDS에 안 보이게 꺼 둔다(host 모듈 instance_metadata_tags)"
  type        = map(string)
  default = {
    Project   = "moayeyak"
    ManagedBy = "terraform"
  }
}
