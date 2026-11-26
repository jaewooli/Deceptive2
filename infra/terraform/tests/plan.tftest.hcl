# terraform test — AWS 자격증명 없이 plan 동작을 확인(mock provider: 아무것도 안 만듦).
#   cd infra/terraform && terraform test
# 보는 것: 팜 중첩 가상화 켜짐/꺼짐(metal), 투영 ENI가 주어진 주소로 생김, 웹훅 대상 조건, 투영 개수 검증

mock_provider "aws" {
  mock_data "aws_ssm_parameter" {
    defaults = { insecure_value = "ami-0123456789abcdef0" }
  }
  mock_data "aws_ami" {
    defaults = { name = "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-20261017" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "111122223333" }
  }
  mock_data "aws_region" {
    defaults = { region = "ap-northeast-2" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::mock-bucket" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::111122223333:role/mock" }
  }
  mock_resource "aws_cloudwatch_event_api_destination" {
    defaults = { arn = "arn:aws:events:ap-northeast-2:111122223333:api-destination/mock" }
  }
}

variables {
  admin_ip = "203.0.113.4/32"
}

run "servers_only" {
  command = plan

  assert {
    condition     = length(output.hosts) == 5
    error_message = "서버 5대(web-01·app-01·db-backup-01·sensor·farm)"
  }
  assert {
    condition     = output.farm_nested_virtualization == true
    error_message = "m8i 팜은 중첩 가상화를 켜야 함"
  }
  assert {
    condition     = length(output.projection_enis) == 0
    error_message = "첫 apply엔 투영 ENI 없음(투영 주소 두 단계)"
  }
  assert {
    condition     = length(module.cloudtrail.rule_name) > 0
    error_message = "웹훅이 없어도 EventBridge 규칙은 있어야 함"
  }
  assert {
    condition     = endswith(output.server_ami.name, "20261017")
    error_message = "AMI 이름(serial)이 출력돼야 함"
  }
}

run "metal_farm" {
  command = plan
  variables {
    farm_instance_type = "m7i.metal-24xl"
  }
  assert {
    condition     = output.farm_nested_virtualization == false
    error_message = "metal 팜엔 중첩 옵션을 넣지 않음"
  }
}

run "with_projections" {
  command = plan
  variables {
    projections = {
      "stg-01" = { segment = "public", ip = "10.0.1.12", device_index = 1 }
      "dev-01" = { segment = "internal", ip = "10.0.2.11", device_index = 2 }
    }
  }
  assert {
    condition     = output.projection_enis["stg-01"].ip == "10.0.1.12" && output.projection_enis["dev-01"].segment == "internal"
    error_message = "투영 ENI가 주어진 주소·구간으로"
  }
  assert {
    condition     = output.projection_enis["dev-01"].ifname_guess == "ens7"
    error_message = "device_index 2 → ens7 추정"
  }
}

run "too_many_projections" {
  command = plan
  variables {
    projections = {
      "a" = { segment = "public", ip = "10.0.1.20", device_index = 1 }
      "b" = { segment = "public", ip = "10.0.1.21", device_index = 2 }
      "c" = { segment = "internal", ip = "10.0.2.20", device_index = 1 }
    }
  }
  expect_failures = [var.projections]
}

run "bad_segment" {
  command = plan
  variables {
    projections = {
      "a" = { segment = "farm", ip = "10.0.3.20", device_index = 1 }
    }
  }
  expect_failures = [var.projections]
}

run "with_webhook" {
  command = plan
  variables {
    alert_webhook_url = "https://example.invalid/webhook"
  }
  assert {
    condition     = length(module.cloudtrail.rule_name) > 0
    error_message = "웹훅을 줘도 규칙은 그대로"
  }
}
