data "aws_region" "current" {}

# ---------------------------------------------------------------- VPC
# SSM·CloudWatch 가 DNS 로 엔드포인트를 해석하므로 DNS 지원/호스트네임을 켠다.
resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.project}-vpc" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = { Name = "${var.project}-igw" }
}

# ---------------------------------------------------------------- 서브넷
# public — web-01. 인터넷에서 80/443 수신(단, 보안 그룹으로 내 공인 IP 만 허용).
resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.public_subnet_cidr
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = true

  tags = { Name = "${var.project}-public" }
}

# internal — app-01, db-backup-01.
#
# NAT 게이트웨이 금지(비용). 내부 서버도 아웃바운드(OS 패치, 웹훅 경보 송신,
# SSM 에이전트의 AWS 엔드포인트 접속, CloudWatch 로그 푸시)가 필요하다.
# 그래서 NAT 대신 "공인 IP + IGW 라우트"로 아웃바운드를 주고(map_public_ip_on_launch
# = true, 아래 internal 라우트가 0.0.0.0/0 -> IGW), 외부에서의 유입 차단은
# 라우팅이 아니라 "보안 그룹 인바운드"로만 한다(security 모듈: 10.0.0.0/16 에서만 허용).
# 대가: SG 설정이 틀리면 바로 노출됨(NAT 구조엔 애초에 유입 경로가 없음) — 비용 위해 감수.
resource "aws_subnet" "internal" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.internal_subnet_cidr
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = true

  tags = { Name = "${var.project}-internal" }
}

# ---------------------------------------------------------------- 라우팅
# public: 0.0.0.0/0 -> IGW
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  tags = { Name = "${var.project}-public-rt" }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# internal: 0.0.0.0/0 -> IGW (no-NAT 트릭, 위 internal 서브넷 주석 참고)
resource "aws_route_table" "internal" {
  vpc_id = aws_vpc.this.id

  tags = { Name = "${var.project}-internal-rt" }
}

resource "aws_route" "internal_internet" {
  route_table_id         = aws_route_table.internal.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "internal" {
  subnet_id      = aws_subnet.internal.id
  route_table_id = aws_route_table.internal.id
}

# ---------------------------------------------------------------- S3 게이트웨이 엔드포인트
# 무료. app-01 의 pg_dump -> S3 백업이 인터넷을 거치지 않게 한다.
# 게이트웨이 엔드포인트는 라우트 테이블에 prefix list 라우트를 추가하는 방식 → 두 RT 모두 연결.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.name}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.public.id, aws_route_table.internal.id]

  tags = { Name = "${var.project}-s3-gw" }
}
