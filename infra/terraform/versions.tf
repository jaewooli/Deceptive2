terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # state 는 로컬 (S3/DynamoDB 백엔드 없음 → 추가 비용 0, .gitignore 로 커밋 금지).
  # 단일 작업자 랩이라 로컬 state 로 충분하다.
}
