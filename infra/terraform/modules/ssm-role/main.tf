# 세 서버 공통 EC2 인스턴스 역할 — SSM Session Manager(관리 접속) + CloudWatch 에이전트.
# 관리 접속은 SSM 뿐이라 SSH 인바운드를 열지 않는다(security 모듈).

variable "project" {
  type = string
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.project}-ssm-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json

  tags = { Name = "${var.project}-ssm-role" }
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "cloudwatch" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_instance_profile" "this" {
  name = "${var.project}-ssm-profile"
  role = aws_iam_role.this.name
}

output "instance_profile_name" {
  value = aws_iam_instance_profile.this.name
}

output "role_name" {
  description = "11/27 에 app-01 S3 백업 권한(backup-writer)을 이 역할에 추가하거나 별도 프로파일로 분리할 때 참조"
  value       = aws_iam_role.this.name
}
