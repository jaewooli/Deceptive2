"""월간 매장 리포트

예약 집계를 백업 서버의 DB 사본에서 읽어 와 본 DB 부하를 피하던 기능.
백업을 S3로 옮긴 뒤로 사본이 갱신되지 않아 REPORT_ENABLED=false 로 꺼 둠.
"""
from flask import Blueprint, render_template
from sqlalchemy import text

from .models import db
from .views.admin import login_required

bp = Blueprint("reports", __name__, url_prefix="/admin/reports")

MONTHLY_SQL = text(
    """
    SELECT s.name, date_trunc('month', r.reserved_at) AS month, count(*) AS cnt
      FROM reservations r JOIN stores s ON s.id = r.store_id
     GROUP BY s.name, month
     ORDER BY month DESC, cnt DESC
    """
)


@bp.get("/monthly")
@login_required
def monthly():
    engine = db.engines["report"]
    with engine.connect() as conn:
        rows = conn.execute(MONTHLY_SQL).all()
    return render_template("admin/monthly.html", rows=rows)
