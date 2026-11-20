from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for

from ..models import Reservation, Store, db
from ..receipt import build_receipt_pdf

bp = Blueprint("public", __name__)


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/healthz")
def healthz():
    return "ok"


@bp.get("/stores")
def stores():
    items = Store.query.filter_by(is_active=True).order_by(Store.name).all()
    return render_template("stores.html", stores=items)


@bp.route("/stores/<int:store_id>/reserve", methods=["GET", "POST"])
def reserve(store_id):
    store = db.get_or_404(Store, store_id)
    if request.method == "POST":
        form = request.form
        try:
            reserved_at = datetime.strptime(f"{form['date']} {form['time']}", "%Y-%m-%d %H:%M")
            party_size = int(form.get("party_size", 1))
        except (KeyError, ValueError):
            flash("날짜와 시간을 확인해 주세요.")
            return render_template("reserve.html", store=store), 400
        name = form.get("customer_name", "").strip()
        phone = form.get("customer_phone", "").strip()
        if not name or not phone or not 1 <= party_size <= 20:
            flash("이름, 연락처, 인원을 확인해 주세요.")
            return render_template("reserve.html", store=store), 400
        r = Reservation(
            store=store,
            customer_name=name,
            customer_phone=phone,
            party_size=party_size,
            reserved_at=reserved_at,
            memo=form.get("memo", "").strip()[:200],
        )
        db.session.add(r)
        db.session.commit()
        return redirect(url_for("public.reservation", code=r.code))
    return render_template("reserve.html", store=store)


@bp.get("/reservations/<code>")
def reservation(code):
    r = Reservation.query.filter_by(code=code).first_or_404()
    return render_template("reservation.html", r=r)


@bp.route("/reservations/<code>/edit", methods=["GET", "POST"])
def reservation_edit(code):
    r = Reservation.query.filter_by(code=code).first_or_404()
    if not r.can_modify():
        flash("이미 지났거나 변경할 수 없는 예약입니다.")
        return redirect(url_for("public.reservation", code=r.code))
    if request.method == "POST":
        form = request.form
        try:
            reserved_at = datetime.strptime(f"{form['date']} {form['time']}", "%Y-%m-%d %H:%M")
            party_size = int(form.get("party_size", r.party_size))
            editcode = form.get("code", "").strip()
        except (KeyError, ValueError):
            flash("날짜와 시간을 확인해 주세요.")
            return render_template("reservation_edit.html", r=r), 400
        if reserved_at <= datetime.now() or not 1 <= party_size <= 20:
            flash("예약 시각과 인원을 확인해 주세요.")
            return render_template("reservation_edit.html", r=r), 400
        if editcode and Reservation.query.filter_by(code=editcode).first():
            flash("이미 존재하는 예약 번호입니다.")
            return render_template("reservation_edit.html", r=r), 400
        r.reserved_at = reserved_at
        r.party_size = party_size
        r.memo = form.get("memo", "").strip()[:200]
        r.code = editcode
        db.session.commit()
        flash("예약을 변경했습니다.")
        return redirect(url_for("public.reservation", code=r.code))
    return render_template("reservation_edit.html", r=r)


@bp.get("/reservations/<code>/receipt.pdf")
def receipt(code):
    r = Reservation.query.filter_by(code=code).first_or_404()
    path = build_receipt_pdf(r)
    if not path:
        abort(500)
    return send_file(path, mimetype="application/pdf", download_name=f"moayeyak-{r.code}.pdf")
