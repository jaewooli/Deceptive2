# T6 미끼(backup-legacy 키)의 AWS 쪽 탐지 = 시나리오 2 "2차"(plan-wbs 5절, 기준 5분 이내).
#   CloudTrail 추적(단일 리전, CLAUDE.md) → 기본 이벤트 버스 → EventBridge 규칙(사용자 이름 backup-legacy) → 웹훅.
#
# 읽기 전용 호출: 키를 얻은 공격자가 제일 먼저 하는 건 `aws sts get-caller-identity`(읽기 전용, 권한 없어도 성공).
#   EventBridge 기본 규칙(ENABLED)은 변경 이벤트만 받는다 → state = ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS,
#   그리고 추적이 읽기 이벤트까지 기록해야 한다(read_write_type = All). AWS 문서:
#   https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-service-event-cloudtrail-management.html
# 키 ID로 맞추지 않고 사용자 이름으로: 키는 Terraform 밖에서 만든다(modules/iam-backup). 교체해도 규칙은 그대로.
#
# ⚠️ 리전 한계(11/26 확인, 사용자 결정 대기): 추적·규칙이 서울 리전 하나라, 공격자가 다른 리전 엔드포인트로 키를 쓰면
#   (예: CLI 기본 리전 us-east-1, 또는 STS 전역 엔드포인트 → 이벤트는 us-east-1에 기록) 이 규칙에 안 온다.
#   대응 후보: 추적을 다중 리전으로 + 규칙을 us-east-1에도. README "알려진 한계".

variable "project" {
  type = string
}

variable "suffix" {
  type = string
}

variable "watch_user" {
  description = "감시할 IAM 사용자 이름(backup-legacy)"
  type        = string
}

variable "enable_webhook" {
  description = "웹훅 대상 붙이기(웹훅 URL이 있을 때)"
  type        = bool
}

variable "webhook_url" {
  type      = string
  default   = null
  sensitive = true
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  trail_name = "${var.project}-trail"
  trail_arn  = "arn:aws:cloudtrail:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:trail/${local.trail_name}"
}

# ---------------------------------------------------------------- 추적 로그 버킷
resource "aws_s3_bucket" "trail" {
  bucket        = "${var.project}-trail-${var.suffix}"
  force_destroy = true # destroy 때 로그까지 지움(랩 정리). 결과 보고에 필요한 로그는 그 전에 내려받기

  tags = { Name = "${var.project}-trail" }
}

resource "aws_s3_bucket_public_access_block" "trail" {
  bucket                  = aws_s3_bucket.trail.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "trail_bucket" {
  statement {
    sid       = "AclCheck"
    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.trail.arn]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.trail_arn]
    }
  }
  statement {
    sid       = "Write"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.trail.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.trail_arn]
    }
  }
}

resource "aws_s3_bucket_policy" "trail" {
  bucket = aws_s3_bucket.trail.id
  policy = data.aws_iam_policy_document.trail_bucket.json
}

# ---------------------------------------------------------------- 추적 (단일 리전, 관리 이벤트 읽기+쓰기)
resource "aws_cloudtrail" "this" {
  name                          = local.trail_name
  s3_bucket_name                = aws_s3_bucket.trail.id
  is_multi_region_trail         = false # CLAUDE.md "CloudTrail 추적은 단일 리전" — 위 리전 한계
  include_global_service_events = true  # IAM 같은 전역 서비스 이벤트
  enable_log_file_validation    = true  # 로그 변조 확인(보고서 근거 자료)

  event_selector {
    read_write_type           = "All" # 읽기 전용(sts get-caller-identity 등)도 — EventBridge 읽기 이벤트의 전제
    include_management_events = true
  }

  depends_on = [aws_s3_bucket_policy.trail]
}

# ---------------------------------------------------------------- EventBridge 규칙
resource "aws_cloudwatch_event_rule" "legacy_key" {
  name        = "${var.project}-legacy-key-use"
  description = "any API call by ${var.watch_user}"
  state       = "ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS"

  event_pattern = jsonencode({
    "detail-type" = ["AWS API Call via CloudTrail"]
    detail = {
      userIdentity = {
        type     = ["IAMUser"]
        userName = [var.watch_user]
      }
    }
  })
}

# ---------------------------------------------------------------- 웹훅 대상(선택) — API 목적지
# 연결(connection)은 인증 방식이 필수라 쓰지 않는 헤더를 둔다(Discord 웹훅은 URL 자체가 비밀). 값은 Secrets Manager에 저장됨.
resource "aws_cloudwatch_event_connection" "webhook" {
  count              = var.enable_webhook ? 1 : 0
  name               = "${var.project}-webhook"
  authorization_type = "API_KEY"
  auth_parameters {
    api_key {
      key   = "X-Notify"
      value = "1"
    }
  }
}

resource "aws_cloudwatch_event_api_destination" "webhook" {
  count                            = var.enable_webhook ? 1 : 0
  name                             = "${var.project}-webhook"
  connection_arn                   = aws_cloudwatch_event_connection.webhook[0].arn
  invocation_endpoint              = var.webhook_url
  http_method                      = "POST"
  invocation_rate_limit_per_second = 5
}

data "aws_iam_policy_document" "events_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "events" {
  count              = var.enable_webhook ? 1 : 0
  name               = "${var.project}-events-webhook"
  assume_role_policy = data.aws_iam_policy_document.events_assume.json
}

resource "aws_iam_role_policy" "events" {
  count = var.enable_webhook ? 1 : 0
  name  = "invoke-webhook"
  role  = aws_iam_role.events[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "events:InvokeApiDestination"
      Resource = aws_cloudwatch_event_api_destination.webhook[0].arn
    }]
  })
}

resource "aws_cloudwatch_event_target" "webhook" {
  count     = var.enable_webhook ? 1 : 0
  rule      = aws_cloudwatch_event_rule.legacy_key.name
  target_id = "webhook"
  arn       = aws_cloudwatch_event_api_destination.webhook[0].arn
  role_arn  = aws_iam_role.events[0].arn

  # Discord 웹훅 형식({"content": ...}) — 서버 경보(moa-notify, notify.format discord)와 같은 수신처
  input_transformer {
    input_paths = {
      event  = "$.detail.eventName"
      source = "$.detail.eventSource"
      ip     = "$.detail.sourceIPAddress"
      agent  = "$.detail.userAgent"
      key    = "$.detail.userIdentity.accessKeyId"
      err    = "$.detail.errorCode"
      region = "$.detail.awsRegion"
      time   = "$.detail.eventTime"
    }
    input_template = <<-EOT
      {"content": "[AWS] ${var.watch_user} 키 사용: <source> <event> (오류 <err>) 출발 <ip> 키 <key> 리전 <region> 시각 <time> UA <agent>"}
    EOT
  }
}

output "trail_arn" {
  value = aws_cloudtrail.this.arn
}

output "trail_bucket" {
  value = aws_s3_bucket.trail.bucket
}

output "rule_name" {
  value = aws_cloudwatch_event_rule.legacy_key.name
}
