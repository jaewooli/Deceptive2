"""예약 확인서 PDF

HTML 템플릿을 렌더링한 뒤 weasyprint(apt: weasyprint, fonts-nanum)로 PDF 변환.
"""
import os
import subprocess
from datetime import datetime

from flask import current_app, render_template

WEASYPRINT = "/usr/bin/weasyprint"


def build_receipt_pdf(reservation):
    """예약 확인서 PDF를 만들고 파일 경로를 반환한다."""
    out_dir = current_app.config["RECEIPT_DIR"]
    os.makedirs(out_dir, exist_ok=True)
    html_path = os.path.join(out_dir, f"{reservation.code}.html")
    pdf_path = os.path.join(out_dir, f"{reservation.code}.pdf")

    html = render_template("receipt.html", r=reservation, issued_at=datetime.now())
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    try:
        subprocess.run(
            [WEASYPRINT, "--quiet", html_path, pdf_path],
            check=True,
            timeout=30,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        current_app.logger.error("receipt pdf failed: %s %s", reservation.code, e)
        return None
    finally:
        try:
            os.remove(html_path)
        except OSError:
            pass
    return pdf_path
