terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # 11/26: 5.x → 6.x. 팜(KVM 디코이 VM)에 중첩 가상화 CPU 옵션(cpu_options.nested_virtualization)이 필요한데
      # 5.100.0 스키마엔 없음(amd_sev_snp·core_count·threads_per_core뿐), 6.74.0엔 있음 — 스키마로 확인
      version = "~> 6.74"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6" # 버킷 이름 난수 6자리(moayeyak-db-backup-<난수6>, CLAUDE.md 이름 규칙)
    }
  }

  # state 는 로컬 (S3/DynamoDB 백엔드 없음, .gitignore 로 커밋 금지).
  # 단일 작업자 랩이라 로컬 state 로 충분하다. state엔 계정 ID·리소스 ID가 평문으로 들어간다.
  # 비밀값(backup-legacy 액세스 키)은 Terraform으로 만들지 않는다 — state에 평문으로 남기 때문(README "비밀값").
}
