# S3 버킷 2개.
#   1) 백업 버킷 moayeyak-db-backup-<난수6> — app-01 pg_dump cron이 IAM 역할 backup-writer로 넣는다(02-infra 4절 "현재").
#      공격자가 app-01에서 IMDS 역할 자격증명으로 `aws s3 ls`하면 이 내용이 보인다 → 진짜 덤프가 쌓여야 함(가짜 파일 넣지 않음).
#      객체 시각(LastModified)은 되돌릴 수 없다 → 서사(S3 전환 2025-09)와 어긋나는 한계. 30일 만료를 두면 구축 30일 뒤부터는
#      "오래 운영된 버킷의 최근 30일"과 같은 모양이 된다(그 전엔 객체가 적음 — 한계로 기록).
#   2) 운영 버킷 moayeyak-ops-<난수6> — 관리 쪽 전용: 미끼 레지스트리(HANDOFF 4절 8번), SSM으로 서버에 보낼 큰 파일.
#      서버로 받는 URL(사전 서명)이 서버 감사 로그에 남을 수 있어 이름에 프로젝트 용어 금지. 레지스트리를 잃으면 미끼 ID → 위치를 못 찾으므로 버전 관리.

variable "project" {
  type = string
}

resource "random_id" "suffix" {
  byte_length = 3 # 16진수 6자리
}

locals {
  suffix = random_id.suffix.hex
}

# ---------------------------------------------------------------- 백업 버킷
resource "aws_s3_bucket" "backup" {
  bucket = "${var.project}-db-backup-${local.suffix}"

  tags = { Name = "${var.project}-db-backup" }
}

resource "aws_s3_bucket_public_access_block" "backup" {
  bucket                  = aws_s3_bucket.backup.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id

  rule {
    id     = "expire-30d"
    status = "Enabled"
    filter {}
    expiration {
      days = 30
    }
  }
}

# ---------------------------------------------------------------- 운영 버킷
resource "aws_s3_bucket" "ops" {
  bucket = "${var.project}-ops-${local.suffix}"

  tags = { Name = "${var.project}-ops" }
}

resource "aws_s3_bucket_public_access_block" "ops" {
  bucket                  = aws_s3_bucket.ops.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "ops" {
  bucket = aws_s3_bucket.ops.id
  versioning_configuration {
    status = "Enabled"
  }
}

output "backup_bucket" {
  value = aws_s3_bucket.backup.bucket
}

output "backup_bucket_arn" {
  value = aws_s3_bucket.backup.arn
}

output "ops_bucket" {
  value = aws_s3_bucket.ops.bucket
}

output "suffix" {
  value = local.suffix
}
