# 보안 그룹. 아웃바운드는 모두 허용(패치·웹훅·SSM·CloudWatch).
# internal 서버의 외부 격리는 전적으로 여기 "인바운드" 규칙으로 한다(NAT 없음, network 모듈 주석 참조).
#
# 이름 주의(11/26): 보안 그룹 "이름"은 서버 안에서 IMDS(meta-data/security-groups)로 보인다.
#   예전 디코이 SG 이름 `moayeyak-decoy-sg` 는 디코이 안에서 curl 한 번에 "decoy"를 보여 줬음 → 서사 이름(호스트 이름)으로.
#   설명(description)은 IMDS에 안 나오지만(API·콘솔만) 같은 원칙으로 프로젝트 용어를 쓰지 않는다. 근거는 이 주석과 README에.
# 터널(WireGuard): 센서·EDH가 PersistentKeepalive로 먼저 연결 → 팜만 인바운드를 연다(상태 저장 SG라 응답은 통과).

variable "project" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  description = "VPC 내부 대역 — 회사 서버·디코이 인바운드 허용 출처"
  type        = string
}

variable "admin_ip" {
  description = "web-01 80/443 을 허용할 내 공인 IP (/32 CIDR)"
  type        = string
}

variable "edh_decoy_ports" {
  description = "호스트별 트랩 포트(EDH 빈 포트 → 팜 트랩). 키는 web-01·app-01"
  type        = map(list(number))
}

locals {
  edh_sg = {
    "web-01" = aws_security_group.web.id
    "app-01" = aws_security_group.app.id
  }
  edh_rules = { for r in flatten([
    for host, ports in var.edh_decoy_ports : [for p in ports : { host = host, port = p }]
  ]) : "${r.host}-${r.port}" => r }
}

# ---------------------------------------------------------------- web-01
# 80/443 ← 내 공인 IP 만. 의도적 RCE 가 있는 호스트라 인터넷 전면 공개하지 않음
# (공개 노출 실험 12/2~ 때만 개방). 관리 접속은 SSM.
resource "aws_security_group" "web" {
  name        = "${var.project}-web-sg"
  description = "web-01: http/https from office IP"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.project}-web-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "web_http" {
  security_group_id = aws_security_group.web.id
  cidr_ipv4         = var.admin_ip
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  description       = "HTTP from office IP"
}

resource "aws_vpc_security_group_ingress_rule" "web_https" {
  security_group_id = aws_security_group.web.id
  cidr_ipv4         = var.admin_ip
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "HTTPS from office IP"
}

resource "aws_vpc_security_group_egress_rule" "web_all" {
  security_group_id = aws_security_group.web.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "all outbound"
}

# ---------------------------------------------------------------- app-01
# 22, 5432 ← VPC 내부(10.0.0.0/16)만. 웹 → 내부 DB 통신은 실제 회사처럼 허용.
resource "aws_security_group" "app" {
  name        = "${var.project}-app-sg"
  description = "app-01: ssh/postgres from VPC"
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

# ---------------------------------------------------------------- EDH 트랩 포트 (web-01 8080, app-01 6379 ← VPC)
# 레지스트리의 active decoy_port 배치와 같아야 한다(variables.tf edh_decoy_ports). 규칙 이름은 서비스 이름처럼.
resource "aws_vpc_security_group_ingress_rule" "edh" {
  for_each          = local.edh_rules
  security_group_id = local.edh_sg[each.value.host]
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "tcp"
  from_port         = each.value.port
  to_port           = each.value.port
  description       = "tcp ${each.value.port} from VPC"
}

# ---------------------------------------------------------------- db-backup-01
# 모든 포트 ← VPC 내부만. 정상 업무에서 아무도 접속하지 않는 서버 → "접속 자체가 신호".
# 이름은 호스트 이름(서버 안 IMDS에 보임 — 위 이름 주의).
resource "aws_security_group" "db_backup" {
  name        = "${var.project}-db-backup-sg"
  description = "db-backup-01: from VPC"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.project}-db-backup-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "db_backup_all" {
  security_group_id = aws_security_group.db_backup.id
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "-1"
  description       = "all from VPC"
}

resource "aws_vpc_security_group_egress_rule" "db_backup_all" {
  security_group_id = aws_security_group.db_backup.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "all outbound"
}

# ---------------------------------------------------------------- sensor 관리 ENI
# 인바운드 없음(관리 = SSM, 팜 터널은 센서가 먼저 연결). 스캔하면 열린 포트 없는 주소.
resource "aws_security_group" "relay" {
  name        = "${var.project}-relay-sg"
  description = "relay: no inbound, management via SSM"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.project}-relay-sg" }
}

resource "aws_vpc_security_group_egress_rule" "relay_all" {
  security_group_id = aws_security_group.relay.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "all outbound"
}

# ---------------------------------------------------------------- sensor 투영 ENI (투영 디코이 주소)
# db-backup-01과 같은 원칙: 모든 포트 ← VPC만. 들어온 연결은 센서가 출발지 그대로 팜 디코이 VM으로 넘긴다.
resource "aws_security_group" "relay_in" {
  name        = "${var.project}-relay-in-sg"
  description = "relay edge: from VPC"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.project}-relay-in-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "relay_in_all" {
  security_group_id = aws_security_group.relay_in.id
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "-1"
  description       = "all from VPC"
}

resource "aws_vpc_security_group_egress_rule" "relay_in_all" {
  security_group_id = aws_security_group.relay_in.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "all outbound"
}

# ---------------------------------------------------------------- farm
# UDP 51820 ← 센서 관리 ENI(relay 터널), UDP 51821~51829 ← web-01·app-01(EDH 트랩 터널 edhN, 51820+N — engine.py).
# 그 밖엔 회사 망에서 팜으로 오는 길이 없다.
resource "aws_security_group" "farm" {
  name        = "${var.project}-farm-sg"
  description = "farm: wireguard tunnels only"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.project}-farm-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "farm_relay" {
  security_group_id            = aws_security_group.farm.id
  referenced_security_group_id = aws_security_group.relay.id
  ip_protocol                  = "udp"
  from_port                    = 51820
  to_port                      = 51820
  description                  = "wireguard relay"
}

resource "aws_vpc_security_group_ingress_rule" "farm_edh" {
  for_each                     = local.edh_sg
  security_group_id            = aws_security_group.farm.id
  referenced_security_group_id = each.value
  ip_protocol                  = "udp"
  from_port                    = 51821
  to_port                      = 51829
  description                  = "wireguard ${each.key}"
}

resource "aws_vpc_security_group_egress_rule" "farm_all" {
  security_group_id = aws_security_group.farm.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "all outbound (ssm, apt snapshot mirror)"
}

output "web_sg_id" {
  value = aws_security_group.web.id
}

output "app_sg_id" {
  value = aws_security_group.app.id
}

output "db_backup_sg_id" {
  value = aws_security_group.db_backup.id
}

output "relay_sg_id" {
  value = aws_security_group.relay.id
}

output "relay_in_sg_id" {
  value = aws_security_group.relay_in.id
}

output "farm_sg_id" {
  value = aws_security_group.farm.id
}
