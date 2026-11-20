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
