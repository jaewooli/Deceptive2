output "vpc_id" {
  description = "VPC ID"
  value       = module.network.vpc_id
}

output "public_subnet_id" {
  description = "public 서브넷 ID (web-01)"
  value       = module.network.public_subnet_id
}

output "internal_subnet_id" {
  description = "internal 서브넷 ID (app-01, db-backup-01)"
  value       = module.network.internal_subnet_id
}

output "web_01" {
  description = "web-01 인스턴스 ID·공인/사설 IP"
  value = {
    instance_id = module.web_01.instance_id
    public_ip   = module.web_01.public_ip
    private_ip  = module.web_01.private_ip
  }
}

output "app_01" {
  value = {
    instance_id = module.app_01.instance_id
    public_ip   = module.app_01.public_ip
    private_ip  = module.app_01.private_ip
  }
}

output "db_backup_01" {
  description = "디코이 — 보조 사설 IP 포함"
  value = {
    instance_id           = module.db_backup_01.instance_id
    public_ip             = module.db_backup_01.public_ip
    private_ip            = module.db_backup_01.private_ip
    secondary_private_ips = module.db_backup_01.secondary_private_ips
  }
}
