# 재사용 EC2 호스트 1대. web-01 / app-01 / db-backup-01 / sensor / farm 을 이 모듈로 부른다.
# 차이는 파라미터로만: 서브넷·타입·SG·인스턴스 프로파일·디스크·중첩 가상화.
#
# ENI 를 명시 생성하는 이유: 인스턴스를 다시 만들어도(타입 변경 등) 같은 ENI = 같은 사설 IP·MAC이 유지된다
#   (미끼·보안 그룹·디코이 서사는 사설 IP 기준 — CLAUDE.md). NAT 금지라 공인 IP가 필요한데, 명시 ENI엔 자동 공인 IP가 안 붙어 EIP로 준다.
# 세 회사 서버는 같은 모양이어야 한다(디코이만 다르면 단서): 같은 AMI·타입·IMDS 설정·디스크·user_data 없음.

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
  description = "인스턴스 프로파일 이름. 이름은 서버 안 IMDS(iam/info)에 보인다"
  type        = string
}

variable "root_volume_size" {
  type    = number
  default = 8
}

variable "nested_virtualization" {
  description = "중첩 가상화(팜만 — 디코이 KVM VM). C8i·M8i·R8i 계열에서만 지원, metal은 필요 없음"
  type        = bool
  default     = false
}

resource "aws_network_interface" "this" {
  subnet_id       = var.subnet_id
  security_groups = [var.security_group_id]
  # source_dest_check 기본(켜짐) 유지: 센서는 투영 주소(= 그 ENI의 주소)로만 받고 내보내고, EDH는 이중 DNAT 뒤 자기 주소로 응답 → 끌 필요 없음

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

  primary_network_interface {
    network_interface_id = aws_network_interface.this.id
  }

  dynamic "cpu_options" {
    for_each = var.nested_virtualization ? [1] : []
    content {
      nested_virtualization = "enabled"
    }
  }

  # 커스텀 user_data 없음 — 공통 베이스·미끼는 SSM 한 채널로(서버 동일성·멱등성·기만 흔적 최소).

  metadata_options {
    http_tokens                 = "required" # IMDSv2 강제
    http_endpoint               = "enabled"
    http_put_response_hop_limit = 2          # Ubuntu 24.04 AMI(ImdsSupport v2.0) 기본값과 같게 — 모든 서버 같은 값
    instance_metadata_tags      = "disabled" # 태그(Name·Project·ManagedBy)를 IMDS로 안 보이게 — 서버 안에서 "terraform" 같은 단서 금지
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_size
    encrypted   = true
  }

  lifecycle {
    # AMI가 새로 나와도 서버를 교체하지 않는다(교체 = 호스트 키·데이터·서사 흔적 소실, 11/23 호스트 키 사고).
    # 패치는 서버 안 unattended-upgrades로(진짜 회사처럼). AMI를 바꾸려면 의도적으로 -replace.
    ignore_changes = [ami]
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

output "mac" {
  value = aws_network_interface.this.mac_address
}
