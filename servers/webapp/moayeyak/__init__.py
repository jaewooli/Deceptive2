import click
from flask import Flask

from .config import Config
from .models import db


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    if app.config["REPORT_ENABLED"] and app.config["REPORT_DB_URL"]:
        app.config["SQLALCHEMY_BINDS"] = {"report": app.config["REPORT_DB_URL"]}

    db.init_app(app)

    from .views.public import bp as public_bp
    from .views.admin import bp as admin_bp
    from .reports import bp as reports_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)
    if app.config["REPORT_ENABLED"]:
        app.register_blueprint(reports_bp)

    _register_commands(app)
    return app


def _register_commands(app):
    from .models import AdminUser, Store

    @app.cli.command("init-db")
    def init_db():
        """테이블 생성"""
        db.create_all(bind_key=None)
        click.echo("ok")

    @app.cli.command("create-admin")
    @click.argument("username")
    @click.password_option()
    def create_admin(username, password):
        """관리자 계정 추가"""
        user = AdminUser(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"created {username}")

    @app.cli.command("seed")
    def seed():
        """개발용 매장 데이터"""
        if Store.query.count():
            click.echo("skip: stores exist")
            return
        db.session.add_all(
            [
                Store(name="소담 헤어", category="미용실", address="서울 마포구 연남로 12", phone="02-333-1204"),
                Store(name="온기 필라테스", category="운동", address="서울 성동구 왕십리로 88", phone="02-2294-0815"),
                Store(name="하루 네일", category="네일", address="서울 송파구 백제고분로 41", phone="02-412-7730"),
            ]
        )
        db.session.commit()
        click.echo("seeded")
