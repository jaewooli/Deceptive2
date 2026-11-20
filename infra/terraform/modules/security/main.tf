# 보안 그룹 3개. 아웃바운드는 모두 허용(패치·웹훅·SSM·CloudWatch).
# internal 서버의 외부 격리는 전적으로 여기 "인바운드" 규칙으로 한다(NAT 없음, network 모듈 주석 참조).

variable "project" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  description = "VPC 내부 대역 — app-01·디코이 인바운드 허용 출처"
  type        = string
}

variable "admin_ip" {
  description = "web-01 80/443 을 허용할 내 공인 IP (/32 CIDR)"
  type        = string
}

# ---------------------------------------------------------------- web-01
# 80/443 ← 내 공인 IP 만. 의도적 RCE 가 있는 호스트라 인터넷 전면 공개하지 않음
# (공개 노출 실험 12/2~ 때만 개방). 관리 접속은 SSM.
resource "aws_security_group" "web" {
  name        = "${var.project}-web-sg"
  description = "web-01: 80/443 from admin IP only; management via SSM"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.project}-web-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "web_http" {
  security_group_id = aws_security_group.web.id
  cidr_ipv4         = var.admin_ip
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  description       = "HTTP from admin IP"
}

resource "aws_vpc_security_group_ingress_rule" "web_https" {
  security_group_id = aws_security_group.web.id
  cidr_ipv4         = var.admin_ip
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "HTTPS from admin IP"
}

resource "aws_vpc_security_group_egress_rule" "web_all" {
  security_group_id = aws_security_group.web.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "all outbound (patch, SSM, CloudWatch, app-01 DB)"
}

# ---------------------------------------------------------------- app-01
# 22, 5432 ← VPC 내부(10.0.0.0/16)만. 웹 → 내부 DB 통신은 실제 회사처럼 허용.
resource "aws_security_group" "app" {
  name        = "${var.project}-app-sg"
  description = "app-01: ssh/postgres from VPC only"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.project}-app-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "app_ssh" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  description       = "SSH from VPC"
}

resource "aws_vpc_security_group_ingress_rule" "app_pg" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "tcp"
  from_port         = 5432
  to_port           = 5432
  description       = "PostgreSQL from VPC"
}

resource "aws_vpc_security_group_egress_rule" "app_all" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "all outbound"
}

# ---------------------------------------------------------------- db-backup-01 (디코이)
# 모든 포트 ← VPC 내부만. 정상 업무에서 아무도 접속하지 않는 서버 → "접속 자체가 신호".
resource "aws_security_group" "decoy" {
  name        = "${var.project}-decoy-sg"
  description = "db-backup-01 decoy: all ports from VPC only (any connection is a signal)"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.project}-decoy-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "decoy_all" {
  security_group_id = aws_security_group.decoy.id
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "-1"
  description       = "all ports from VPC (connection itself is the alert)"
}

resource "aws_vpc_security_group_egress_rule" "decoy_all" {
  security_group_id = aws_security_group.decoy.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "all outbound"
}

output "web_sg_id" {
  value = aws_security_group.web.id
}

output "app_sg_id" {
  value = aws_security_group.app.id
}

output "decoy_sg_id" {
  value = aws_security_group.decoy.id
}
