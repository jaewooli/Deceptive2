from datetime import datetime
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from ..models import AdminUser, Reservation, db

bp = Blueprint("admin", __name__, url_prefix="/admin")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("admin.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = AdminUser.query.filter_by(username=request.form.get("username", "")).first()
        if user and user.check_password(request.form.get("password", "")):
            session.clear()
            session["admin_id"] = user.id
            user.last_login_at = datetime.now()
            db.session.commit()
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/admin") else url_for("admin.dashboard"))
        flash("아이디 또는 비밀번호가 올바르지 않습니다.")
    return render_template("admin/login.html")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("public.index"))


@bp.get("/")
@login_required
def dashboard():
    items = Reservation.query.order_by(Reservation.reserved_at.desc()).limit(100).all()
    return render_template("admin/dashboard.html", reservations=items)
