# 재사용 EC2 호스트 1대. web-01 / app-01 / db-backup-01 을 이 모듈로 3번 호출한다.
# 차이는 파라미터로만: 서브넷·타입·SG·보조 IP 개수.
#
# ENI 를 명시 생성하는 이유: 디코이의 "단일 호스트 다중 주소"(보조 사설 IP) 때문.
# NAT 금지라 공인 IP 가 필요한데, 명시 ENI 에는 자동 공인 IP 가 안 붙으므로 EIP 로 준다.
# (세 호스트 모두 EIP 로 통일 — 분기 없음. 공인 IPv4 비용은 설계가 이미 반영.)

variable "project" {
  type = string
}

variable "name" {
  description = "호스트 이름 (web-01 등)"
  type        = string
}

variable "ami_id" {
  type = string
}

variable "instance_type" {
  type = string
}

variable "subnet_id" {
  type = string
}

variable "security_group_id" {
  type = string
}

variable "iam_instance_profile" {
  description = "SSM 인스턴스 프로파일 이름 (11/27 app-01 은 S3 백업 권한 포함 프로파일로 교체 가능)"
  type        = string
}

variable "secondary_ip_count" {
  description = "보조 사설 IP 개수 (디코이=3, 나머지=0). ENI 총 IP = 1 + 이 값, t3.small 은 ENI당 4개까지."
  type        = number
  default     = 0
}

variable "root_volume_size" {
  type    = number
  default = 8
}

resource "aws_network_interface" "this" {
  subnet_id         = var.subnet_id
  security_groups   = [var.security_group_id]
  private_ips_count = var.secondary_ip_count

  tags = { Name = "${var.project}-${var.name}-eni" }
}

resource "aws_eip" "this" {
  domain            = "vpc"
  network_interface = aws_network_interface.this.id

  tags = { Name = "${var.project}-${var.name}-eip" }
}

resource "aws_instance" "this" {
  ami                  = var.ami_id
  instance_type        = var.instance_type
  iam_instance_profile = var.iam_instance_profile

  network_interface {
    device_index         = 0
    network_interface_id = aws_network_interface.this.id
  }

  # 커스텀 user_data 없음 — 공통 베이스·미끼는 SSM/Ansible 한 채널로(세 서버 동일성·멱등성·기만 흔적 최소).

  metadata_options {
    http_tokens   = "required" # IMDSv2 강제
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_size
    encrypted   = true
  }

  tags = { Name = "${var.project}-${var.name}" }
}

output "instance_id" {
  value = aws_instance.this.id
}

output "private_ip" {
  value = aws_network_interface.this.private_ip
}

output "public_ip" {
  value = aws_eip.this.public_ip
}

output "secondary_private_ips" {
  value = aws_network_interface.this.private_ips
}
