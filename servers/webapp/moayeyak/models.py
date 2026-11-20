import secrets
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def _reservation_code():
    return secrets.token_hex(4).upper()


class Store(db.Model):
    __tablename__ = "stores"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    category = db.Column(db.String(40), nullable=False)
    address = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    reservations = db.relationship("Reservation", back_populates="store")


class Reservation(db.Model):
    __tablename__ = "reservations"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(16), unique=True, nullable=False, default=_reservation_code)
    store_id = db.Column(db.Integer, db.ForeignKey("stores.id"), nullable=False)
    customer_name = db.Column(db.String(40), nullable=False)
    customer_phone = db.Column(db.String(20), nullable=False)
    party_size = db.Column(db.Integer, nullable=False, default=1)
    reserved_at = db.Column(db.DateTime, nullable=False)
    memo = db.Column(db.String(200), nullable=False, default="")
    status = db.Column(db.String(16), nullable=False, default="confirmed")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    store = db.relationship("Store", back_populates="reservations")

    def can_modify(self, now=None):
        """확정 상태이고 예약 시각이 아직 지나지 않았을 때만 변경할 수 있다."""
        now = now or datetime.now()
        return self.status == "confirmed" and self.reserved_at > now


class AdminUser(db.Model):
    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    last_login_at = db.Column(db.DateTime)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
