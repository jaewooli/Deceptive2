variable "project" {
  description = "리소스 Name 접두사"
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR"
  type        = string
}

variable "public_subnet_cidr" {
  description = "public 서브넷 CIDR"
  type        = string
}

variable "internal_subnet_cidr" {
  description = "internal 서브넷 CIDR"
  type        = string
}

variable "availability_zone" {
  description = "두 서브넷을 둘 단일 AZ"
  type        = string
}
