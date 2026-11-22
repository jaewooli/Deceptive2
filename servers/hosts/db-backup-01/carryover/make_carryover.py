#!/usr/bin/env python3
"""재구축(2026-11) 때 옛 백업 서버에서 rsync -a로 옮겨 온 것을 만든다. db-backup-01에서 root로 한 번 실행하고, 이 디렉터리는 지운다.
  sudo python3 -I make_carryover.py --app-ip 10.0.2.10

만드는 것 (docs/02-infra-design.md 4절 서사, validation/checks.md A·C·F)
  - `backup` 계정(uid 34, 배포판 기본)을 쓰던 상태로: 홈 /backup, 셸 bash, bash_history, rrsync 제한 키(app-01발)
  - /backup/dumps: app-01이 매일 밤 rsync로 보낸 pg_dump. 보존 정책 = 최근 30개 + 매월 첫 덤프(11/22 결정)
    덤프 머리말의 PG 버전은 그날 noble-security에 있던 버전(Launchpad 배포 이력), 16.10 전에는 \\restrict 줄 없음
  - /backup/bin: 보존 정리·리포트 사본 복원 스크립트, /backup/log/restore.log
  - /etc/cron.d/backup-dumps: S3 전환(2025-09-16) 때 주석 처리된 작업
  - PG `moayeyak` DB: 리포트용 사본(마지막 덤프 복원, 2025-09 스키마 — updated_at 없음), 소유 역할 `moayeyak`(NOLOGIN)
  모든 파일 시각은 서사 날짜(mtime). ctime은 실행일 = 재구축일이라 서사와 맞는다.
데이터는 시드 고정(같은 입력 → 같은 데이터). app-01 운영 DB도 같은 데이터로 이어져야 한다(11/27~28).
"""
import argparse
import gzip
import hashlib
import io
import os
import pwd
import grp
import random
import re
import secrets
import shutil
import subprocess
import tempfile
from datetime import date, datetime, time, timedelta

BUILT = datetime(2024, 6, 12, 14, 21, 37)     # 첫 서버 구축
LAUNCH = date(2024, 6, 14)                    # 운영 시작(첫 덤프 다음 날 새벽)
CUTOVER = datetime(2025, 9, 16, 10, 42, 5)    # rsync·복원 cron 주석 처리(S3 전환 커밋 2025-09-15 18:20 다음 날)
LAST_DUMP = date(2025, 9, 15)
KEEP_DAILY = 30
DB_BUILD = "moayeyak_build"
SEED = 20240612

# noble-security 배포일(https://launchpad.net/ubuntu/+source/postgresql-16/+publishinghistory, 11/22 조회).
# 구축 때는 noble-updates 최신(16.3), 그 뒤는 unattended-upgrades(보안 채널만)가 다음 날 새벽 전에 반영했다고 본다
PG_VERSIONS = [
    (date(2024, 5, 30), "16.3", "16.3-0ubuntu0.24.04.1"),
    (date(2024, 8, 19), "16.4", "16.4-0ubuntu0.24.04.1"),
    (date(2024, 12, 2), "16.6", "16.6-0ubuntu0.24.04.1"),
    (date(2025, 3, 3), "16.8", "16.8-0ubuntu0.24.04.1"),
    (date(2025, 5, 20), "16.9", "16.9-0ubuntu0.24.04.1"),
    (date(2025, 9, 8), "16.10", "16.10-0ubuntu0.24.04.1"),   # pg_dump \restrict 도입(CVE-2025-8714)
]

STORES = [  # 처음 셋은 웹 앱 seed와 같다(servers/webapp/moayeyak/__init__.py)
    ("소담 헤어", "미용실", "서울 마포구 연남로 12", "02-333-1204", "sodam_hair"),
    ("온기 필라테스", "운동", "서울 성동구 왕십리로 88", "02-2294-0815", "ongi_pilates"),
    ("하루 네일", "네일", "서울 송파구 백제고분로 41", "02-412-7730", "haru_nail"),
    ("결 피부관리", "피부관리", "서울 강남구 선릉로 158길 9", "02-545-2017", "gyeol_skin"),
    ("마루 커피로스터스", "카페", "서울 용산구 회나무로 27", "02-794-3361", "maru_coffee"),
    ("봄날 정육식당", "식당", "서울 영등포구 당산로 214", "02-2633-9182", "bomnal"),
    ("새벽 클라이밍", "운동", "경기 성남시 분당구 정자일로 95", "031-711-4420", "saebyeok_climb"),
    ("담음 공방", "공방", "서울 종로구 북촌로 61", "02-765-0193", "dameum"),
    ("이음 헤어", "미용실", "서울 관악구 관악로 152", "02-877-5521", "ieum_hair"),
    ("오롯 요가", "운동", "서울 서대문구 연희로 37", "02-336-8804", "orot_yoga"),
    ("별빛 네일", "네일", "인천 연수구 송도과학로 32", "032-858-1176", "byeolbit_nail"),
    ("한끼 덮밥", "식당", "서울 동작구 상도로 289", "02-812-6630", "hankki"),
    ("숲 반려견 미용", "반려동물", "경기 고양시 일산동구 중앙로 1261", "031-905-2248", "soop_pet"),
    ("느린 사진관", "사진관", "서울 마포구 와우산로 29", "02-325-7712", "neurin_photo"),
]
STORE_OPEN = [date(2024, 6, 14)] * 3 + [date(2024, 7, 2), date(2024, 8, 19), date(2024, 9, 30), date(2024, 11, 11),
              date(2025, 1, 6), date(2025, 2, 24), date(2025, 3, 31), date(2025, 5, 12), date(2025, 6, 9),
              date(2025, 7, 21), date(2025, 8, 25)]
CLOSED = {"hankki": date(2025, 4, 30)}  # 폐업한 매장 하나(is_active=false)

SURN = "김이박최정강조윤장임한오서신권황안송류홍전고문양손배백허남심노"
GIVEN = ["서연", "민준", "지우", "서준", "하은", "도윤", "수아", "예준", "지민", "주원", "하린", "시우", "유진", "건우",
         "다은", "현우", "채원", "지호", "수빈", "은우", "소율", "준서", "윤서", "태윤", "가은", "민서", "예린", "승현"]
MEMOS = ["", "", "", "", "", "", "창가 자리 부탁드려요", "조금 늦을 수 있어요", "아이 동반", "주차 가능할까요?",
         "처음 방문", "지난번 담당 선생님으로", "알레르기 있어요(견과류)", "커트만", "10분 일찍 도착 예정"]


def sh(*cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def psql(db, sql, user="postgres"):
    return subprocess.run(["runuser", "-u", user, "--", "psql", "-XqAt", "-v", "ON_ERROR_STOP=1", "-d", db],
                          input=sql, text=True, check=True, capture_output=True).stdout


def stamp(path, when, owner=None, mode=None):
    if owner:
        u, g = owner
        os.chown(path, pwd.getpwnam(u).pw_uid, grp.getgrnam(g).gr_gid)
    if mode is not None:
        os.chmod(path, mode)
    t = when.timestamp()
    os.utime(path, (t, t))


def pg_version(d):
    cur = None
    for since, short, full in PG_VERSIONS:
        if since < d:  # 배포 다음 날 새벽 덤프부터
            cur = (short, full)
    return cur


def werkzeug_scrypt(rng):
    """werkzeug 3 generate_password_hash 기본 형식(scrypt:32768:8:1$salt$hex). 비밀번호는 버린다."""
    salt = "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789") for _ in range(16))
    pw = secrets.token_urlsafe(24)
    h = hashlib.scrypt(pw.encode(), salt=salt.encode(), n=32768, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=64)
    return f"scrypt:32768:8:1${salt}${h.hex()}"


def q(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int,)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


SCHEMA = """
CREATE TABLE stores (
    id SERIAL NOT NULL, name VARCHAR(80) NOT NULL, category VARCHAR(40) NOT NULL, address VARCHAR(200) NOT NULL,
    phone VARCHAR(20) NOT NULL, is_active BOOLEAN NOT NULL, created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id));
CREATE TABLE admin_users (
    id SERIAL NOT NULL, username VARCHAR(40) NOT NULL, password_hash VARCHAR(256) NOT NULL,
    last_login_at TIMESTAMP WITHOUT TIME ZONE, PRIMARY KEY (id), UNIQUE (username));
CREATE TABLE reservations (
    id SERIAL NOT NULL, code VARCHAR(16) NOT NULL, store_id INTEGER NOT NULL, customer_name VARCHAR(40) NOT NULL,
    customer_phone VARCHAR(20) NOT NULL, party_size INTEGER NOT NULL, reserved_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    memo VARCHAR(200) NOT NULL, status VARCHAR(16) NOT NULL, created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id), UNIQUE (code), FOREIGN KEY(store_id) REFERENCES stores (id));
ALTER TABLE stores OWNER TO moayeyak; ALTER TABLE admin_users OWNER TO moayeyak; ALTER TABLE reservations OWNER TO moayeyak;
"""


class World:
    """운영 데이터를 날짜 순서로 만든다. day(d)는 그날 일어난 일을 SQL로 낸다."""

    def __init__(self):
        self.rng = random.Random(SEED)
        self.codes = set()
        self.store_ids = {}
        self.pending_logins = {}

    def phone(self):
        # 010-0xxx는 이동전화에 배정되지 않는 대역 → 실존 번호와 겹치지 않음
        return f"010-0{self.rng.randint(100, 999)}-{self.rng.randint(1000, 9999)}"

    def day(self, d, with_updated=False, cutoff=None):
        """cutoff: 이 시각 뒤의 일은 아직 안 일어난 것(운영 DB의 오늘 하루에만 씀 — 그 뒤 날이 없으니 난수 순서가 달라져도 무관)"""
        out = []
        late = (lambda t: cutoff is not None and t > cutoff)
        for i, (name, cat, addr, tel, user) in enumerate(STORES):
            if STORE_OPEN[i] == d:
                t = datetime.combine(d, time(10 + i % 5, self.rng.randint(0, 59), self.rng.randint(0, 59)))
                out.append(f"INSERT INTO stores (name, category, address, phone, is_active, created_at) VALUES "
                           f"({q(name)}, {q(cat)}, {q(addr)}, {q(tel)}, true, {q(t)});")
                out.append(f"INSERT INTO admin_users (username, password_hash) VALUES ({q(user)}, {q(werkzeug_scrypt(self.rng))});")
                self.store_ids[user] = len(self.store_ids) + 1
            if CLOSED.get(user) == d:
                out.append(f"UPDATE stores SET is_active = false WHERE name = {q(name)};")
        resv = []  # (생성 시각, SQL) — id가 생성 순서대로 늘어나게 하루치를 시각순으로 넣는다
        for user, sid in self.store_ids.items():
            if user in CLOSED and d >= CLOSED[user]:
                continue
            age = (d - STORE_OPEN[sid - 1]).days
            base = 2 + min(age, 240) / 30          # 문을 연 지 오래될수록 예약이 늘어난다
            if d.weekday() >= 5:
                base *= 1.6
            n = max(0, int(self.rng.gauss(base, base / 3)))
            for _ in range(n):
                created = datetime.combine(d, time(self.rng.randint(8, 23), self.rng.randint(0, 59), self.rng.randint(0, 59)))
                reserved = datetime.combine(d + timedelta(days=self.rng.choice([0, 1, 1, 2, 3, 4, 5, 7, 10, 14])),
                                            time(self.rng.choice([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]),
                                                 self.rng.choice([0, 30])))
                if reserved <= created:
                    reserved += timedelta(days=1)
                code = secrets.token_hex(4).upper()
                while code in self.codes:
                    code = secrets.token_hex(4).upper()
                self.codes.add(code)
                status = "cancelled" if self.rng.random() < 0.07 else "confirmed"
                name = self.rng.choice(SURN) + self.rng.choice(GIVEN)
                party = self.rng.choice([1, 1, 1, 2, 2, 2, 3, 4]) if self.rng.random() < 0.9 else self.rng.randint(5, 12)
                cols, vals = "", ""
                if with_updated:
                    cols, vals = ", updated_at", f", {q(created)}"
                if late(created):
                    continue
                resv.append((created, "INSERT INTO reservations (code, store_id, customer_name, customer_phone, party_size, reserved_at, "
                           f"memo, status, created_at{cols}) VALUES ({q(code)}, {sid}, {q(name)}, {q(self.phone())}, {party}, "
                           f"{q(reserved)}, {q(self.rng.choice(MEMOS))}, {q(status)}, {q(created)}{vals});"))
            if self.rng.random() < 0.6:  # 사장님 로그인
                t = datetime.combine(d, time(self.rng.randint(9, 22), self.rng.randint(0, 59), self.rng.randint(0, 59)))
                if not late(t):
                    out.append(f"UPDATE admin_users SET last_login_at = {q(t)} WHERE username = {q(user)};")
        out.extend(sql for _, sql in sorted(resv, key=lambda x: x[0]))
        if with_updated:  # 2025-10-21 예약 변경 기능 뒤: 하루 몇 건은 손님이 예약을 고친다(앞으로 올 예약만)
            for _ in range(self.rng.randint(0, 6)):
                t = datetime.combine(d, time(self.rng.randint(9, 22), self.rng.randint(0, 59), self.rng.randint(0, 59)))
                if late(t):
                    continue
                out.append("UPDATE reservations SET party_size = GREATEST(1, party_size + " + str(self.rng.choice([-1, 1, 1, 2])) +
                           f"), updated_at = {q(t)} WHERE id = (SELECT id FROM reservations WHERE status = 'confirmed' AND reserved_at > {q(t)} "
                           f"AND created_at < {q(t)} ORDER BY md5(id::text || {q(str(d))}) LIMIT 1);")
        return out


def dump_dates():
    days = [LAUNCH + timedelta(days=i) for i in range((LAST_DUMP - LAUNCH).days + 1)]
    keep = set(days[-KEEP_DAILY:])
    seen = set()
    for d in days:  # 매월 첫 덤프
        if (d.year, d.month) not in seen:
            seen.add((d.year, d.month))
            keep.add(d)
    return sorted(keep)


def fix_header(text, d):
    short, full = pg_version(d)
    text = re.sub(r"(-- Dumped (?:from database|by pg_dump) version )\S+ \(Ubuntu [^)]+\)", rf"\g<1>{short} (Ubuntu {full})", text)
    if tuple(map(int, short.split("."))) < (16, 10):  # \restrict는 16.10부터
        text = re.sub(r"^\\(un)?restrict \S+\n\n?", "", text, flags=re.M)
    return text


def dump_at(day, out_path, keep_db):
    """같은 시드의 데이터를 day 새벽 덤프 시점까지 만들고, 그 덤프 하나를 out_path에 쓴 뒤 DB를 keep_db로 남긴다.
    옛 스테이징(stg-01)이 db-backup-01에서 가져와 복원한 덤프 — 데이터가 db-backup-01 덤프와 이어진다"""
    psql("postgres", "DO $$BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='moayeyak') THEN CREATE ROLE moayeyak NOLOGIN; END IF; END$$;")
    psql("postgres", f"DROP DATABASE IF EXISTS {DB_BUILD}; DROP DATABASE IF EXISTS {keep_db}; CREATE DATABASE {DB_BUILD} OWNER moayeyak;")
    psql(DB_BUILD, SCHEMA)
    world, d = World(), LAUNCH
    while d < day:
        stmts = world.day(d)
        if stmts:
            psql(DB_BUILD, "BEGIN;\n" + "\n".join(stmts) + "\nCOMMIT;")
        d += timedelta(days=1)
    raw = subprocess.run(["runuser", "-u", "postgres", "--", "pg_dump", "--no-privileges", DB_BUILD],
                         check=True, capture_output=True, text=True).stdout
    raw = fix_header(raw, day)
    arrived = datetime.combine(day, time(3, 17, 41))
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=int(arrived.timestamp()) - 40) as g:
        g.write(raw.encode())
    with open(out_path, "wb") as f:
        f.write(buf.getvalue())
    psql("postgres", f"ALTER DATABASE {DB_BUILD} RENAME TO {keep_db};")
    print(f"dump {out_path} reservations={psql(keep_db, 'select count(*) from reservations;').strip()}")


MIGRATION = datetime(2025, 10, 21, 14, 41, 7)  # 예약 변경 기능 배포(커밋 2025-10-21 14:30) 때 손으로 돌린 ALTER


def live(until, password, db="moayeyak"):
    """app-01 운영 DB: 같은 시드로 운영 시작부터 until까지. 2025-10-21에 updated_at 컬럼 추가(그때 있던 행은 마이그레이션 시각)."""
    psql("postgres", f"DO $$BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='moayeyak') THEN CREATE ROLE moayeyak LOGIN; END IF; END$$;"
                     f" ALTER ROLE moayeyak LOGIN PASSWORD {q(password)};")
    psql("postgres", f"DROP DATABASE IF EXISTS {DB_BUILD}; CREATE DATABASE {DB_BUILD} OWNER moayeyak;")
    psql(DB_BUILD, SCHEMA)
    world, d, migrated = World(), LAUNCH, False
    while d <= until:
        if not migrated and d >= MIGRATION.date():
            psql(DB_BUILD, f"ALTER TABLE reservations ADD COLUMN updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT {q(MIGRATION)};"
                           " ALTER TABLE reservations ALTER COLUMN updated_at DROP DEFAULT;")
            migrated = True
        stmts = world.day(d, with_updated=migrated, cutoff=datetime.now() if d == date.today() else None)
        if stmts:
            psql(DB_BUILD, "BEGIN;\n" + "\n".join(stmts) + "\nCOMMIT;")
        d += timedelta(days=1)
    psql("postgres", f"DROP DATABASE IF EXISTS {db}; ALTER DATABASE {DB_BUILD} RENAME TO {db};")
    print(f"live {db} reservations={psql(db, 'select count(*) from reservations;').strip()} "
          f"edited={psql(db, 'select count(*) from reservations where updated_at > created_at;').strip()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", help="YYYY-MM-DD까지 운영 DB(app-01)")
    ap.add_argument("--password", help="--live: moayeyak 역할 비밀번호(web-01 .env와 같게, 배포 때 주입)")
    ap.add_argument("--app-ip", help="app-01 사설 IP(authorized_keys from=)")
    ap.add_argument("--dump-at", help="YYYY-MM-DD: 그날 덤프 하나만 만들고 DB를 남김(옛 스테이징용)")
    ap.add_argument("--dump-out")
    ap.add_argument("--keep-db", default="moayeyak")
    args = ap.parse_args()
    if args.live:
        return live(date.fromisoformat(args.live), args.password or ap.error("--password 필요"))
    if args.dump_at:
        return dump_at(date.fromisoformat(args.dump_at), args.dump_out, args.keep_db)
    if not args.app_ip:
        ap.error("--app-ip 필요")

    # ---- 계정·디렉터리
    sh("usermod", "-d", "/backup", "-s", "/bin/bash", "backup")
    for d in ("/backup", "/backup/dumps", "/backup/bin", "/backup/log", "/backup/.ssh"):
        os.makedirs(d, exist_ok=True)
    for f in (".bashrc", ".profile", ".bash_logout"):
        shutil.copy("/etc/skel/" + f, "/backup/" + f)
        stamp("/backup/" + f, BUILT + timedelta(minutes=3), ("backup", "backup"), 0o644)

    # ---- PG: 소유 역할 + 만들기용 DB
    psql("postgres", "DO $$BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='moayeyak') THEN CREATE ROLE moayeyak NOLOGIN; END IF; END$$;")
    psql("postgres", f"DROP DATABASE IF EXISTS {DB_BUILD}; DROP DATABASE IF EXISTS moayeyak; CREATE DATABASE {DB_BUILD} OWNER moayeyak;")
    psql(DB_BUILD, SCHEMA)

    world, want = World(), set(dump_dates())
    d, restore_log = LAUNCH, []
    sizes = []
    while d <= LAST_DUMP:
        # 덤프는 그날 03:15(app-01), 그 전날까지 일어난 일이 들어 있다
        if d in want:
            raw = subprocess.run(["runuser", "-u", "postgres", "--", "pg_dump", "--no-privileges", DB_BUILD],
                                 check=True, capture_output=True, text=True).stdout
            raw = fix_header(raw.replace(DB_BUILD, "moayeyak"), d)
            arrived = datetime.combine(d, time(3, 16 + world.rng.randint(0, 3), world.rng.randint(0, 59)))
            path = f"/backup/dumps/moayeyak-{d:%Y%m%d}.sql.gz"
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb", mtime=int(arrived.timestamp()) - 40) as g:
                g.write(raw.encode())
            with open(path, "wb") as f:
                f.write(buf.getvalue())
            stamp(path, arrived, ("backup", "backup"), 0o644)  # 복원 cron(postgres)이 읽는다
            sizes.append((d, len(buf.getvalue())))
        if d >= date(2024, 7, 8):  # 리포트 사본 복원(2024-07 리포트 기능부터, 매일 04:30)
            rows = psql(DB_BUILD, "SELECT count(*) FROM reservations;").strip()
            restore_log.append(f"{d:%Y-%m-%d} 04:30:{world.rng.randint(1, 9):02d} restore moayeyak-{d:%Y%m%d}.sql.gz -> moayeyak ok (reservations={rows})")
        if d == LAST_DUMP:
            break
        stmts = world.day(d)
        if stmts:
            psql(DB_BUILD, "BEGIN;\n" + "\n".join(stmts) + "\nCOMMIT;")
        d += timedelta(days=1)

    psql("postgres", f"ALTER DATABASE {DB_BUILD} RENAME TO moayeyak;")

    # ---- 스크립트·로그·cron
    prune = """#!/bin/bash
# 덤프 보존: 최근 30개 + 매월 첫 덤프
set -eu
cd /backup/dumps
ls -1 moayeyak-*.sql.gz | sort > /tmp/.dumps.$$
keep=$( (tail -n 30 /tmp/.dumps.$$; awk -F- '{m=substr($2,1,6)} !seen[m]++' /tmp/.dumps.$$) | sort -u)
for f in $(cat /tmp/.dumps.$$); do echo "$keep" | grep -qx "$f" || rm -f -- "$f"; done
rm -f /tmp/.dumps.$$
"""
    restore = """#!/bin/bash
# 리포트용 사본: 그날 들어온 덤프로 moayeyak DB를 다시 만든다 (web-01 월간 리포트가 report_ro로 읽음)
set -eu
f=/backup/dumps/moayeyak-$(date +%Y%m%d).sql.gz
[ -f "$f" ] || { echo "$(date '+%F %T') no dump $f"; exit 1; }
psql -q -d postgres -c 'DROP DATABASE IF EXISTS moayeyak_new' -c 'CREATE DATABASE moayeyak_new OWNER moayeyak'
gunzip -c "$f" | psql -q -v ON_ERROR_STOP=1 -d moayeyak_new >/dev/null
psql -q -d postgres -c 'DROP DATABASE IF EXISTS moayeyak' -c 'ALTER DATABASE moayeyak_new RENAME TO moayeyak'
echo "$(date '+%F %T') restore $(basename "$f") -> moayeyak ok (reservations=$(psql -At -d moayeyak -c 'select count(*) from reservations'))"
"""
    for name, body, when in (("prune-dumps.sh", prune, BUILT + timedelta(minutes=48)),
                             ("restore-latest.sh", restore, datetime(2024, 7, 8, 16, 2, 41))):
        p = "/backup/bin/" + name
        open(p, "w").write(body)
        stamp(p, when, ("backup", "backup"), 0o755)
    open("/backup/log/restore.log", "w").write("\n".join(restore_log) + "\n")
    stamp("/backup/log/restore.log", datetime.combine(LAST_DUMP, time(4, 30, 9)), ("postgres", "postgres"), 0o644)  # cron이 postgres로 씀
    cron = """# 옛 DB 덤프 수신 서버 작업
# 2025-09-16 S3 전환으로 중단 (app-01 백업은 S3로 바로 올림)
#30 4 * * * postgres /backup/bin/restore-latest.sh >> /backup/log/restore.log 2>&1
#50 4 * * * backup   /backup/bin/prune-dumps.sh
"""
    open("/etc/cron.d/backup-dumps", "w").write(cron)
    stamp("/etc/cron.d/backup-dumps", CUTOVER + timedelta(minutes=2), ("root", "root"), 0o644)

    # ---- app-01발 rsync 키(rrsync로 쓰기 전용 제한). 개인키는 app-01에서 S3 전환 때 지웠다(11/22 결정) → 만들고 버림
    with tempfile.TemporaryDirectory() as t:
        sh("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "backup@app-01", "-f", t + "/k")
        pub = open(t + "/k.pub").read().strip()
    ak = f'restrict,from="{args.app_ip}",command="/usr/bin/rrsync -wo /backup/dumps" {pub}\n'
    open("/backup/.ssh/authorized_keys", "w").write(ak)
    stamp("/backup/.ssh/authorized_keys", BUILT + timedelta(minutes=31), ("backup", "backup"), 0o600)
    stamp("/backup/.ssh", BUILT + timedelta(minutes=31), ("backup", "backup"), 0o700)

    # ---- bash_history: 관리자가 sudo -iu backup으로 들어와 확인하던 명령
    hist = HISTORY.strip("\n") + "\n"
    open("/backup/.bash_history", "w").write(hist)
    stamp("/backup/.bash_history", CUTOVER + timedelta(minutes=3), ("backup", "backup"), 0o600)

    stamp("/backup/log", datetime.combine(LAST_DUMP, time(4, 30, 9)), ("postgres", "backup"), 0o775)
    for p, when in (("/backup/bin", datetime(2024, 7, 8, 16, 2, 41)),
                    ("/backup/dumps", datetime.combine(LAST_DUMP, time(4, 50, 3))), ("/backup", CUTOVER + timedelta(minutes=3))):
        stamp(p, when, ("backup", "backup"), 0o755)  # postgres(복원 cron)가 지나가야 함

    total = sum(s for _, s in sizes)
    print(f"dumps={len(sizes)} first={sizes[0][0]} last={sizes[-1][0]} total={total // 1024} KiB "
          f"last_size={sizes[-1][1] // 1024} KiB reservations={psql('moayeyak', 'select count(*) from reservations;').strip()}")


HISTORY = """
ls -lh /backup/dumps
df -h /backup
crontab -l
ls -lh /backup/dumps | tail
gunzip -c /backup/dumps/moayeyak-20240614.sql.gz | head -40
ls -la ~/.ssh
cat ~/.ssh/authorized_keys
exit
ls -lh /backup/dumps | tail -5
cat /backup/bin/prune-dumps.sh
/backup/bin/prune-dumps.sh
ls /backup/dumps | wc -l
exit
vi /backup/bin/restore-latest.sh
bash -n /backup/bin/restore-latest.sh
tail -n 20 /backup/log/restore.log
exit
df -h /backup
du -sh /backup/dumps
ls -lh /backup/dumps | tail -3
tail -n 5 /backup/log/restore.log
exit
ls -lh /backup/dumps | tail -3
tail -n 3 /backup/log/restore.log
du -sh /backup/dumps
exit
tail -n 3 /backup/log/restore.log
ls -lh /backup/dumps | tail -3
exit
ls -lh /backup/dumps | tail -3
tail -n 3 /backup/log/restore.log
cat /etc/cron.d/backup-dumps
exit
ls -lh /backup/dumps | tail -5
du -sh /backup/dumps
exit
"""

if __name__ == "__main__":
    main()
