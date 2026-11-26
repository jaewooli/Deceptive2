# 백업 서사의 IAM 두 개(02-infra 4절, CLAUDE.md 이름 규칙).
#   backup-writer  — 현재: app-01 인스턴스 역할. pg_dump → S3 cron. 다른 서버와 같은 SSM·CloudWatch 권한 + 백업 버킷 쓰기·목록.
#                   역할·프로파일 이름은 app-01 안 IMDS(iam/info, iam/security-credentials/<역할>)에 보인다 → 서사 이름 그대로.
#   backup-legacy  — 옛날: S3 전환 전 쓰던 IAM 사용자. 정리 안 된 채 권한만 뺐다(T6 미끼의 실제 주인). 권한 0.
#                   키를 쓰면 모든 호출이 거부되지만 CloudTrail에 남는다 → EventBridge 경보(modules/cloudtrail).
#                   액세스 키는 여기서 만들지 않는다: Terraform이 만들면 비밀 키가 state에 평문으로 남는다(11/26 결정).
#                   배포 때 `aws iam create-access-key --user-name backup-legacy`로 만들어 미끼 엔진이 app-01에 주입(README "비밀값").
#   한계: IAM 생성일(CreateDate)은 되돌릴 수 없다(서사상 2024~2025). 키 주인은 `sts get-caller-identity`로 ARN만 보이고
#         날짜를 보려면 iam:GetUser가 필요한데 권한 0이라 공격자에겐 안 보인다.

variable "project" {
  type = string
}

variable "backup_bucket_arn" {
  type = string
}

data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

# ---------------------------------------------------------------- backup-writer (app-01)
resource "aws_iam_role" "backup_writer" {
  name               = "backup-writer"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2.json

  tags = { Name = "backup-writer" }
}

resource "aws_iam_role_policy_attachment" "backup_writer_ssm" {
  role       = aws_iam_role.backup_writer.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "backup_writer_cw" {
  role       = aws_iam_role.backup_writer.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

data "aws_iam_policy_document" "backup_write" {
  statement {
    sid       = "List"
    actions   = ["s3:ListBucket"]
    resources = [var.backup_bucket_arn]
  }
  statement {
    sid       = "Put"
    actions   = ["s3:PutObject"]
    resources = ["${var.backup_bucket_arn}/*"]
  }
}

resource "aws_iam_role_policy" "backup_write" {
  name   = "s3-backup-write"
  role   = aws_iam_role.backup_writer.id
  policy = data.aws_iam_policy_document.backup_write.json
}

resource "aws_iam_instance_profile" "backup_writer" {
  name = "backup-writer"
  role = aws_iam_role.backup_writer.name
}

# ---------------------------------------------------------------- backup-legacy (권한 0, 키 없음)
resource "aws_iam_user" "backup_legacy" {
  name = "backup-legacy"

  tags = { Name = "backup-legacy" }
}

output "backup_writer_profile" {
  value = aws_iam_instance_profile.backup_writer.name
}

output "backup_legacy_arn" {
  value = aws_iam_user.backup_legacy.arn
}

output "backup_legacy_name" {
  value = aws_iam_user.backup_legacy.name
}
