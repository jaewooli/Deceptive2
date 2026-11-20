#!/usr/bin/env python3
"""/srv/app 서사용 커밋 이력 만들기 (서버에 올리지 않음, 결과 디렉터리만 배포)

  python3 servers/webapp-history/build_history.py --out /tmp/srv-app

- 서사 시간표: 운영 시작 2024-03 → S3 전환 2025-09 (docs/02-infra-design.md 4절)
- 마지막 커밋의 트리 = servers/webapp 현재 파일과 같아야 한다(다르면 실패)
- receipt.py(예약 확인서 PDF)는 직접 작성하는 파일이라 실행할 때의 내용을 그대로 쓴다.
  함수를 다 쓴 뒤 다시 실행하면 된다
- 의존성 버전: 각 커밋 날짜 이전에 PyPI에 나온 최신 정식 버전(pypi-release-dates.json 스냅숏)
- 작성자: 가상 개발자 2명, RFC 2606 예약 도메인 moayeyak.example
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SRC = REPO / "servers" / "webapp"

A = ("박지훈", "jihoon@moayeyak.example")  # 창업 개발자
B = ("이서연", "seoyeon@moayeyak.example")  # 2024-09 합류


# ------------------------------------------------------------------ 파일 버전
def F(rel):
    return (SRC / rel).read_text()


def sub(text, old, new, count=1):
    if old not in text:
        raise SystemExit(f"변환 실패: {old[:60]!r} 없음 — webapp 코드가 바뀌었으면 이 도구의 단계도 고쳐야 함")
    return text.replace(old, new, count)


def drop_block(text, start, end=None):
    """start 줄부터 end 직전(없으면 끝)까지 제거"""
    i = text.index(start)
    j = text.index(end, i) if end else len(text)
    return text[:i] + text[j:]


def requirements_at(date):
    snap = json.loads((HERE / "pypi-release-dates.json").read_text())["packages"]
    lines = []
    for line in F("requirements.txt").splitlines():
        name, pinned = line.split("==")
        rel = snap.get(name)
        if rel is None:
            raise SystemExit(f"{name}: 스냅숏에 없음 → pypi-release-dates.json 갱신 필요")
        cands = [v for v, d in rel.items() if d <= date]
        if not cands:
            raise SystemExit(f"{name}: {date} 이전 버전 없음")
        best = max(cands, key=lambda v: tuple(int(x) for x in v.split(".")))
        lines.append(f"{name}=={best}")
    return "\n".join(lines) + "\n"


def check_final_requirements(date):
    snap = json.loads((HERE / "pypi-release-dates.json").read_text())["packages"]
    for line in F("requirements.txt").splitlines():
        name, v = line.split("==")
        d = snap.get(name, {}).get(v)
        if d is None or d > date:
            raise SystemExit(f"{name}=={v} 배포일({d})이 마지막 의존성 커밋({date})보다 늦음")


def v_init(stage):
    t = F("moayeyak/__init__.py")
    if stage < 13:  # 리포트 끄기 전
        t = sub(t, '    if app.config["REPORT_ENABLED"] and app.config["REPORT_DB_URL"]:\n',
                '    if app.config["REPORT_DB_URL"]:\n')
        t = sub(t, '    if app.config["REPORT_ENABLED"]:\n        app.register_blueprint(reports_bp)\n',
                '    app.register_blueprint(reports_bp)\n')
    if stage < 7:  # 리포트 전
        t = drop_block(t, '    if app.config["REPORT_DB_URL"]:\n', "    db.init_app(app)")
        t = sub(t, "    from .reports import bp as reports_bp\n", "")
        t = sub(t, "    app.register_blueprint(reports_bp)\n", "")
    if stage < 4:  # 관리자 전
        t = sub(t, "    from .views.admin import bp as admin_bp\n", "")
        t = sub(t, "    app.register_blueprint(admin_bp)\n", "")
        t = sub(t, "from .models import AdminUser, Store", "from .models import Store")
        t = drop_block(t, '    @app.cli.command("create-admin")', '    @app.cli.command("seed")')
    return t


def v_config(stage):
    t = F("moayeyak/config.py")
    if stage < 13:
        t = sub(t, "    # 월간 매장 리포트: 백업 서버 DB에서 조회하던 기능.\n    # 백업을 S3로 옮기면서 비활성화 (REPORT_ENABLED=false)\n    REPORT_ENABLED = _flag(\"REPORT_ENABLED\")\n",
                "    # 월간 매장 리포트: 백업 서버의 DB 사본에서 조회 (본 DB 부하 분리)\n")
        t = sub(t, 'def _flag(name, default="false"):\n    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")\n\n\n', "")
    if stage < 7:
        t = drop_block(t, "    # 월간 매장 리포트")
        t = t.rstrip("\n") + "\n"
    if stage < 9:
        t = sub(t, '    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}\n', "")
    if stage < 6:
        t = drop_block(t, "\n    # 예약 확인서 PDF")
        t = t.rstrip("\n") + "\n"
    return t


def v_reports(stage):
    t = F("moayeyak/reports.py")
    if stage < 13:
        t = sub(t, '"""월간 매장 리포트\n\n예약 집계를 백업 서버의 DB 사본에서 읽어 와 본 DB 부하를 피하던 기능.\n백업을 S3로 옮긴 뒤로 사본이 갱신되지 않아 REPORT_ENABLED=false 로 꺼 둠.\n"""',
                '"""월간 매장 리포트\n\n예약 집계를 백업 서버의 DB 사본(매일 rsync로 갱신)에서 읽어 와 본 DB 부하를 피한다.\n"""')
    return t


def v_env(stage):
    t = F(".env.example")
    if stage < 13:
        t = sub(t, "# 월간 리포트 (S3 이전 후 비활성)\nREPORT_ENABLED=false\nREPORT_DB_URL=\n",
                "# 월간 리포트: 백업 서버 DB 사본 (읽기 전용 계정)\nREPORT_DB_URL=postgresql+psycopg://report_ro:CHANGE_ME@db-backup-01:5432/moayeyak\n")
    if stage < 7:
        t = drop_block(t, "\n# 월간 리포트")
    if stage < 6:
        t = sub(t, "RECEIPT_DIR=/srv/app/var/receipts\n", "")
    return t


def v_models(stage):
    t = F("moayeyak/models.py")
    if stage < 4:
        t = drop_block(t, "\n\nclass AdminUser")
        t = sub(t, "from werkzeug.security import check_password_hash, generate_password_hash\n", "")
        t = t.rstrip("\n") + "\n"
    if stage < 2:
        t = drop_block(t, "\n\nclass Reservation")
        t = sub(t, '\n    reservations = db.relationship("Reservation", back_populates="store")\n', "")
        t = sub(t, "\n\ndef _reservation_code():\n    return secrets.token_hex(4).upper()\n", "")
        t = sub(t, "import secrets\n", "")
        t = t.rstrip("\n") + "\n"
    return t


def v_public(stage):
    t = F("moayeyak/views/public.py")
    if stage < 6:
        t = drop_block(t, '\n\n@bp.get("/reservations/<code>/receipt.pdf")')
        t = t.rstrip("\n") + "\n"
        t = sub(t, "from ..receipt import build_receipt_pdf\n", "")
        t = sub(t, "abort, flash, redirect, render_template, request, send_file, url_for",
                "flash, redirect, render_template, request, url_for")
    if stage < 5:  # 입력 검증 전
        i = t.index("        form = request.form\n")
        j = t.index("        r = Reservation(")
        t = t[:i] + (
            "        form = request.form\n"
            "        reserved_at = datetime.strptime(f\"{form['date']} {form['time']}\", \"%Y-%m-%d %H:%M\")\n"
            "        name = form.get(\"customer_name\", \"\").strip()\n"
            "        phone = form.get(\"customer_phone\", \"\").strip()\n"
            "        party_size = int(form.get(\"party_size\", 1))\n"
        ) + t[j:]
        t = sub(t, "from flask import Blueprint, flash, redirect,", "from flask import Blueprint, redirect,")
    if stage < 2:
        t = drop_block(t, '\n\n@bp.route("/stores/<int:store_id>/reserve"')
        t = t.rstrip("\n") + "\n"
        t = sub(t, "from datetime import datetime\n\n", "")
        t = sub(t, "from flask import Blueprint, redirect, render_template, request, url_for",
                "from flask import Blueprint, render_template")
        t = sub(t, "from ..models import Reservation, Store, db", "from ..models import Store")
    return t


def v_admin(stage):
    t = F("moayeyak/views/admin.py")
    if stage < 8:  # 이동 경로 제한 전
        t = sub(t, '            nxt = request.args.get("next", "")\n            return redirect(nxt if nxt.startswith("/admin") else url_for("admin.dashboard"))\n',
                '            return redirect(request.args.get("next") or url_for("admin.dashboard"))\n')
    return t


def v_base_html(stage):
    t = F("moayeyak/templates/base.html")
    if stage < 4:
        t = sub(t, "      <a href=\"{{ url_for('admin.login') }}\">사장님 로그인</a>\n", "")
    return t


def v_stores_html(stage):
    t = F("moayeyak/templates/stores.html")
    if stage < 2:
        t = sub(t, "    <a class=\"btn\" href=\"{{ url_for('public.reserve', store_id=s.id) }}\">예약하기</a>\n", "")
    return t


def v_reservation_html(stage):
    t = F("moayeyak/templates/reservation.html")
    if stage < 6:
        t = sub(t, "<a class=\"btn\" href=\"{{ url_for('public.receipt', code=r.code) }}\">예약 확인서 PDF 받기</a>\n", "")
    return t


def v_nginx(stage):
    t = F("deploy/nginx-moayeyak.conf")
    if stage < 11:
        t = sub(t, "        expires 7d;\n", "")
    return t


def v_install(stage):
    t = F("deploy/install.sh")
    if stage < 6:
        t = drop_block(t, "# 예약 확인서 PDF")
    return t


def v_readme(stage):
    t = F("README.md")
    if stage < 6:
        t = sub(t, "예약 확인서 PDF: `sudo apt install weasyprint fonts-nanum`\n\n", "")
    if stage < 4:
        t = sub(t, ".venv/bin/flask --app wsgi create-admin <id>\n", "")
    if stage < 3:
        t = drop_block(t, "\n## 배포")
        t = t.rstrip("\n") + "\n"
    return t


# ------------------------------------------------------------------ 커밋 단계
# (단계 번호, 날짜시각 KST, 작성자, 메시지, 이 단계에서 쓰는 파일들)
def stages():
    S = []
    def add(n, when, who, msg, files):
        S.append((n, when, who, msg, files))

    common = lambda n: {
        "wsgi.py": F("wsgi.py"), ".gitignore": F(".gitignore"),
        "moayeyak/views/__init__.py": F("moayeyak/views/__init__.py"),
        "moayeyak/static/style.css": F("moayeyak/static/style.css"),
        "moayeyak/templates/index.html": F("moayeyak/templates/index.html"),
    }
    add(1, "2024-03-04T10:12:41", A, "모아예약 웹 시작: Flask 골격, 랜딩·매장 목록", {
        **common(1),
        "requirements.txt": requirements_at("2024-03-04"),
        "README.md": v_readme(1), ".env.example": v_env(1),
        "moayeyak/__init__.py": v_init(1), "moayeyak/config.py": v_config(1),
        "moayeyak/models.py": v_models(1), "moayeyak/views/public.py": v_public(1),
        "moayeyak/templates/base.html": v_base_html(1),
        "moayeyak/templates/stores.html": v_stores_html(1),
    })
    add(2, "2024-03-11T15:03:22", A, "예약 폼과 예약 확인 페이지", {
        "moayeyak/models.py": v_models(2), "moayeyak/views/public.py": v_public(2),
        "moayeyak/templates/stores.html": v_stores_html(2),
        "moayeyak/templates/reserve.html": F("moayeyak/templates/reserve.html"),
        "moayeyak/templates/reservation.html": v_reservation_html(2),
    })
    add(3, "2024-03-14T21:47:05", A, "배포 설정: gunicorn + nginx + systemd", {
        "deploy/moayeyak.service": F("deploy/moayeyak.service"),
        "deploy/nginx-moayeyak.conf": v_nginx(3), "deploy/install.sh": v_install(3),
        "README.md": v_readme(3),
    })
    add(4, "2024-03-20T11:26:58", A, "사장님 로그인과 예약 목록", {
        "moayeyak/models.py": v_models(4), "moayeyak/__init__.py": v_init(4),
        "moayeyak/views/admin.py": v_admin(4), "moayeyak/templates/base.html": v_base_html(4),
        "moayeyak/templates/admin/login.html": F("moayeyak/templates/admin/login.html"),
        "moayeyak/templates/admin/dashboard.html": F("moayeyak/templates/admin/dashboard.html"),
        "README.md": v_readme(4),
    })
    add(5, "2024-04-02T14:10:37", A, "예약 폼 입력 검증 (날짜 형식, 인원 1~20)", {
        "moayeyak/views/public.py": v_public(5),
    })
    add(6, "2024-05-13T16:44:12", A, "예약 확인서 PDF 다운로드", {
        "moayeyak/receipt.py": F("moayeyak/receipt.py"),
        "moayeyak/templates/receipt.html": F("moayeyak/templates/receipt.html"),
        "README.md": v_readme(6), "deploy/install.sh": v_install(6),
        "moayeyak/views/public.py": v_public(6), "moayeyak/config.py": v_config(6),
        "moayeyak/templates/reservation.html": v_reservation_html(6), ".env.example": v_env(6),
    })
    add(7, "2024-07-08T10:58:30", A, "월간 매장 리포트: 백업 서버 DB 사본에서 집계", {
        "moayeyak/reports.py": v_reports(7),
        "moayeyak/templates/admin/monthly.html": F("moayeyak/templates/admin/monthly.html"),
        "moayeyak/__init__.py": v_init(7), "moayeyak/config.py": v_config(7), ".env.example": v_env(7),
    })
    add(8, "2024-09-23T13:35:09", B, "로그인 후 이동 경로를 /admin 아래로 제한", {
        "moayeyak/views/admin.py": v_admin(8),
    })
    add(9, "2024-10-07T17:22:51", B, "DB 재시작 뒤 끊긴 연결 재사용 방지 (pool_pre_ping)", {
        "moayeyak/config.py": v_config(9),
    })
    add(10, "2024-11-25T10:31:16", B, "의존성 업데이트", {"requirements.txt": requirements_at("2024-11-25")})
    add(11, "2025-02-17T15:08:44", B, "정적 파일 캐시 7일", {"deploy/nginx-moayeyak.conf": v_nginx(11)})
    add(12, "2025-05-12T11:47:03", B, "의존성 업데이트", {"requirements.txt": requirements_at("2025-05-12")})
    add(13, "2025-09-15T18:20:27", A,
        "월간 리포트 끔: 백업을 S3로 옮겨 백업 서버 DB 사본이 더 갱신되지 않음\n\n"
        "REPORT_ENABLED 플래그 추가(기본 false). 리포트를 다시 쓰려면 S3 백업에서 읽도록 바꿔야 함", {
        "moayeyak/__init__.py": v_init(13), "moayeyak/config.py": v_config(13),
        "moayeyak/reports.py": v_reports(13), ".env.example": v_env(13),
    })
    add(14, "2025-12-08T14:02:55", B, "의존성 업데이트", {"requirements.txt": requirements_at("2025-12-08")})
    last_dep = "2026-11-18"
    check_final_requirements(last_dep)
    add(15, f"{last_dep}T16:39:40", B, "의존성 업데이트", {"requirements.txt": F("requirements.txt")})
    return S


# ------------------------------------------------------------------ 실행
def git(out, *args, env=None):
    return subprocess.run(["git", "-C", str(out), *args], check=True, env=env,
                          capture_output=True, text=True).stdout


def build(out):
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out}: 비어 있지 않음")
    out.mkdir(parents=True, exist_ok=True)
    git(out, "init", "-q", "-b", "main")
    tree = {}
    for n, when, (name, email), msg, files in stages():
        tree.update(files)
        for rel, content in files.items():
            p = out / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        stamp = f"{when}+09:00"
        env = dict(os.environ, GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email, GIT_AUTHOR_DATE=stamp,
                   GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email, GIT_COMMITTER_DATE=stamp,
                   TZ="Asia/Seoul", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
        git(out, "add", "-A", env=env)
        git(out, "commit", "-q", "--no-verify", "-m", msg, env=env)
    # 마지막 트리 = 현재 webapp
    want = {str(p.relative_to(SRC)) for p in SRC.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    got = set(git(out, "ls-files").split())
    if want != got:
        raise SystemExit(f"파일 목록 다름: 빠짐 {sorted(want - got)}, 남음 {sorted(got - want)}")
    for rel in want:
        if (SRC / rel).read_bytes() != (out / rel).read_bytes():
            raise SystemExit(f"내용 다름: {rel}")
    # 작업 트리 파일 시각 = 그 파일을 마지막으로 바꾼 커밋 시각
    for rel in got:
        ts = int(git(out, "log", "-1", "--format=%ct", "--", rel))
        os.utime(out / rel, (ts, ts))
    if "raise NotImplementedError" in F("moayeyak/receipt.py"):
        print("주의: receipt.py가 아직 빈 함수. build_receipt_pdf()를 작성한 뒤 다시 실행", file=sys.stderr)
    print(git(out, "log", "--format=%ad %an %s", "--date=format:%Y-%m-%d %H:%M"), end="")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    build(args.out)


if __name__ == "__main__":
    main()
