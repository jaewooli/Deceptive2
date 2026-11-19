import os


def _flag(name, default="false"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ["SECRET_KEY"]
    SQLALCHEMY_DATABASE_URI = os.environ["DATABASE_URL"]
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # 예약 확인서 PDF 임시 저장 위치
    RECEIPT_DIR = os.environ.get("RECEIPT_DIR", "/srv/app/var/receipts")

    # 월간 매장 리포트: 백업 서버 DB에서 조회하던 기능.
    # 백업을 S3로 옮기면서 비활성화 (REPORT_ENABLED=false)
    REPORT_ENABLED = _flag("REPORT_ENABLED")
    REPORT_DB_URL = os.environ.get("REPORT_DB_URL", "")
