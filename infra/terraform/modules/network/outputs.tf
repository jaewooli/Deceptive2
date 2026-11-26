output "vpc_id" {
  value = aws_vpc.this.id
}

output "vpc_cidr" {
  value = aws_vpc.this.cidr_block
}

output "public_subnet_id" {
  value = aws_subnet.public.id
}

output "internal_subnet_id" {
  value = aws_subnet.internal.id
}

output "farm_subnet_id" {
  value = aws_subnet.farm.id
}

output "subnet_cidrs" {
  value = {
    public   = aws_subnet.public.cidr_block
    internal = aws_subnet.internal.cidr_block
    farm     = aws_subnet.farm.cidr_block
  }
}

output "igw_id" {
  value = aws_internet_gateway.this.id
}
