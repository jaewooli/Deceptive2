# 출력 = infra/env/aws.yml의 빈 값(~)을 채우는 재료(local-aws-parity 5절, render.py가 엔진·검사로 넘김).
# 값 확인: terraform output -json

output "vpc_id" {
  value = module.network.vpc_id
}

output "subnets" {
  description = "구간 CIDR(aws.yml segments)"
  value       = module.network.subnet_cidrs
}

output "hosts" {
  description = "aws.yml hosts.<이름>.instance_id·ip — 미끼·보안 그룹·서사는 사설 IP 기준(공인 IP는 재시작 때 안 바뀜: EIP)"
  value = {
    for name, h in {
      "web-01"       = module.web_01
      "app-01"       = module.app_01
      "db-backup-01" = module.db_backup_01
      "sensor"       = module.sensor
      "farm"         = module.farm
    } : name => { instance_id = h.instance_id, private_ip = h.private_ip, public_ip = h.public_ip }
  }
}

output "farm_tunnel_endpoint" {
  description = "aws.yml farm.tunnel_endpoint — 센서·EDH의 WireGuard Endpoint(팜 사설 IP)"
  value       = module.farm.private_ip
}

output "farm_nested_virtualization" {
  value = local.farm_nested
}

output "projection_enis" {
  description = "aws.yml segments.<구간>.sensor_nics — OS NIC 이름은 ifname_guess(첫날 MAC으로 확인)"
  value       = module.projection.enis
}

output "server_ami" {
  description = "서버 AMI ID·이름(이름 끝 = serial). 투영 디코이 VM 이미지 = 같은 serial의 클라우드 이미지(aws.yml farm.guest.base_image)"
  value = {
    id   = local.ami_id
    name = data.aws_ami.server.name
  }
}

output "buckets" {
  value = {
    backup = module.storage.backup_bucket # app-01 백업 cron 대상
    ops    = module.storage.ops_bucket    # 미끼 레지스트리·SSM 전송(관리 쪽 전용)
    trail  = module.cloudtrail.trail_bucket
  }
}

output "backup_legacy_arn" {
  description = "T6 미끼 키 주인. 키는 Terraform 밖에서: aws iam create-access-key --user-name backup-legacy"
  value       = module.iam_backup.backup_legacy_arn
}

output "legacy_key_rule" {
  value = module.cloudtrail.rule_name
}
