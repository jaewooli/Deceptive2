#!/usr/bin/env python3
"""구별 단서 판정 (checks.md 43개, 자동 층·사람 층). collect.sh·probe.sh·botprobe.sh 원자료를 받아 항목별로 판정한다.
  python3 -I validation/compare.py <디코이.txt> <app.txt> [--probe <디코이.probe> <app.probe>] [--bot <디코이.bot> <app.bot>] [--addrs <디코이.addrs>] > report.md

판정
  ok     기대 상태와 맞음
  clue   구별 단서
  na     그 서버에는 해당 없음(역할 차이)
  skip   이번 측정에서 잴 수 없음(이유 표시)
분류: 디코이 clue + app ok/na → 디코이 전용 단서 / 둘 다 clue → 공통 단서(서사를 깨는 단서, 따로 셈)
로컬 VM에서만 생기는 원인은 note에 [로컬]로 표시하고 개수에서 따로 센다.
"""
import re
import sys
from datetime import date, timedelta

START, CUT = "2024-06", "2025-09"          # 서사: 구축·운영 시작 → S3 전환(이후 방치) → 2026-11 재구축(11/22)
LAUNCH, LAST_DUMP = "2024-06-14", "2025-09-15"  # 덤프 기간(make_carryover.py와 같음)
TERMS = re.compile(r"\b(deceptive2?|honeypot|honeytoken|decoy|canary|cowrie|lure|bait)\b", re.I)


def load(path):
    d, cur = {}, None
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.match(r"^### (\S+)", line)
        if m:
            cur = m.group(1)
            d[cur] = []
        elif cur:
            d[cur].append(line.rstrip("\n"))
    return d


def kv(lines, key):
    for l in lines:
        if l.startswith(key + "="):
            return l.split("=", 1)[1]
    return ""


def ym(s):
    m = re.search(r"(\d{4})-(\d{2})", s)
    return f"{m.group(1)}-{m.group(2)}" if m else ""


def first_date(lines):
    for l in lines:
        m = re.search(r"\d{4}-\d{2}-\d{2}", l)
        if m:
            return m.group(0)
    return ""


class Host:
    def __init__(self, path, probe=None, bot=None):
        self.s = load(path)
        if probe:
            for k, v in load(probe).items():
                self.s["probe_" + k] = v
        if bot:
            self.s.update(load(bot))
        self.name = kv(self.s.get("META", []), "hostname")
        self.now = date.fromisoformat(kv(self.s["META"], "collected_at")[:10])

    def __getitem__(self, k):
        return self.s.get(k, [])


# ---------------------------------------------------------------- 항목 규칙
# 각 규칙: (host, role) -> (판정, 근거[, note])   role = "decoy" | "app"
RULES = {}


def rule(i, kind, roles=("decoy", "app")):
    def deco(f):
        RULES[i] = (kind, roles, f)
        return f
    return deco


def after_cut(d):
    return bool(d) and d[:7] > CUT


def rebuild(h):
    """이 서버의 재구축일 = 첫 부팅 때 만들어지는 machine-id 날짜(EC2에선 IMDS pendingTime과 같은 날이어야 함)"""
    return first_date(h["B5"])


def ago(h, d, days):
    return bool(d) and date.fromisoformat(d) >= h.now - timedelta(days=days)


@rule("A1", "⏱")
def a1(h, r):
    rb = rebuild(h)
    begins = next((l for l in h["A1"] if l.startswith("wtmp begins")), "")
    users = {l.split()[0] for l in h["A1"] if l and not l.startswith(("reboot", "wtmp", "-")) and len(l.split()) > 3}
    if r == "decoy" and "backup" in users:
        return "clue", "재구축 뒤 `backup` 로그인 기록이 있음"
    return "ok", f"wtmp는 재구축({rb}) 뒤부터, 로그인 사용자 {sorted(users) or '없음'}"


@rule("A2", "⏱", ("decoy",))
def a2(h, r):
    line = next((l for l in h["A2"] if l.split()[:1] == ["backup"]), "")
    return ("clue", f"새 서버에 `backup` 로그인 기록: {line.strip()}") if line else ("ok", "`backup` 새 서버 로그인 없음(옛 lastlog는 안 옮김)")


@rule("A3", "⏱", ("decoy",))
def a3(h, r):
    line = next((l for l in h["A3"] if l.startswith("backup ")), "")
    if not line or "없음" in line:
        return "clue", "`backup` 히스토리 없음"
    m = re.search(r"mtime=(\S+)", line)
    return ("ok" if m and m.group(1)[:7] == CUT else "clue"), line.split("  ")[0]


@rule("A4", "⏱")
def a4(h, r):
    # 옮겨 온 홈(backup)은 옛 날짜에 퍼져 있어야 하고, 재구축 뒤 만든 관리자 홈(ubuntu·root)은 최근이어도 된다
    if r != "decoy":
        return "ok", "운영 서버 관리자 홈은 재구축 뒤 것(옮겨 온 서비스 계정 홈은 11/27 이후 확인)"
    line = next((l for l in h["A4"] if l.startswith("backup ")), "")
    if not line:
        return "clue", "`backup` 홈 없음"
    cnt = {p.rsplit(":", 1)[0]: int(p.rsplit(":", 1)[1]) for p in line.split()[1:]}
    tot, old = sum(cnt.values()), sum(v for k, v in cnt.items() if START <= k <= CUT)
    months = sorted(k for k in cnt if START <= k <= CUT)
    ok = tot and old / tot >= 0.9 and len(months) >= 6
    return ("ok" if ok else "clue"), f"`backup` 파일 {old}/{tot}개가 {START}~{CUT}, {len(months)}개 달에 퍼짐"


@rule("A5", "⏱")
def a5(h, r):
    rb = rebuild(h)
    olds = [l[:10] for l in h["A5"] if re.match(r"\d{4}-\d{2}-\d{2} /var/log/", l)]
    too_old = [d for d in olds if d[:7] < "2026-10"]
    return ("clue", f"재구축 전 날짜의 시스템 로그: {too_old}") if too_old else ("ok", f"시스템 로그는 이미지 빌드·재구축({rb}) 뒤 것만(옛 로그는 안 옮김)")


@rule("A6", "⏱")
def a6(h, r):
    first, rb = first_date(h["A6"][1:2]), rebuild(h)
    return ("ok" if first == rb else "clue"), f"저널 첫 부팅 {first}, 재구축(machine-id) {rb}"


@rule("A7", "⏱")
def a7(h, r):
    first, rb = kv(h["A7"], "apt_first"), rebuild(h)
    serial = kv([l.replace(": ", "=") for l in h["B6"]], "serial")
    img = f"{serial[:4]}-{serial[4:6]}-{serial[6:8]}" if serial else ""
    ok = first and (not img or first >= img) and (not rb or first <= rb)
    return ("ok" if ok else "clue"), f"apt 이력 {first}(이미지 빌드 {img}) ~ {kv(h['A7'], 'apt_last')}, {kv(h['A7'], 'apt_runs')}회"


@rule("A8", "⏱")
def a8(h, r):
    reboots = sum(1 for l in h["A8"] if l.startswith("reboot"))
    boots = int(kv(h["A6"], "boots") or 0)
    rotated = any("/var/log/wtmp.1" in l for l in h["A1"])
    if reboots == boots or rotated:
        return "ok", f"wtmp 재부팅 {reboots}회 = 저널 부팅 {boots}회"
    return "clue", f"wtmp 재부팅 {reboots}회 ≠ 저널 부팅 {boots}회"


def gfs_expected():
    days, d = [], date.fromisoformat(LAUNCH)
    while d <= date.fromisoformat(LAST_DUMP):
        days.append(d)
        d += timedelta(days=1)
    keep, seen = set(days[-30:]), set()
    for d in days:
        if d.strftime("%Y-%m") not in seen:
            seen.add(d.strftime("%Y-%m"))
            keep.add(d)
    out = {}
    for d in keep:
        out[d.strftime("%Y-%m")] = out.get(d.strftime("%Y-%m"), 0) + 1
    return out


@rule("A9", "⏱", ("decoy",))
def a9(h, r):
    if any("없음" in l for l in h["A9"]):
        return "clue", "`/backup/dumps` 없음"
    rows = [l for l in h["A9"] if re.match(r"\d{4}-\d{2}-\d{2} \d+ ", l)]
    first, last = (rows[0][:10], rows[-1][:10]) if rows else ("", "")
    got = {p.split(":")[0]: int(p.split(":")[1]) for p in kv(h["A9"], "months").split()}
    want = gfs_expected()
    bad = sorted(set(got) ^ set(want)) + [m for m in want if m in got and got[m] != want[m]]
    msg = f"{kv(h['A9'], 'count')}개 {first}~{last}"
    return ("clue", msg + f", 보존 정책과 다른 달: {bad}") if bad else ("ok", msg + ", 보존 정책(최근 30개 + 매월 첫 덤프)대로")


@rule("A10", "⏱", ("decoy",))
def a10(h, r):
    n = int(kv(h["A10"], "rsync_lines") or 0)
    return ("clue", f"새 서버에 rsync 기록 {n}줄") if n else ("ok", "새 서버엔 rsync 수신 기록 없음(재구축 전에 멈춤)")


@rule("B1", "⏱")
def b1(h, r):
    d, rb = first_date(h["B1"]), rebuild(h)
    inst = sum(1 for l in h["B1"] if l.startswith("d"))
    note = f"[로컬] cloud-init 인스턴스 {inst}개 — vm.sh가 켤 때마다 instance-id를 새로 만들던 것(11/22 고침)" if inst > 1 else ""
    return ("ok" if inst == 1 else "clue"), f"cloud-init {d}, 인스턴스 {inst}개(재구축 {rb})", note


@rule("B2", "⏱")
def b2(h, r):
    late = []
    for l in h["B2"]:
        m = re.match(r"(\S+) utc=(\d+) kst=(\d+) utc_after_kst=(\d+)", l)
        if m and int(m.group(4)):
            late.append(f"{m.group(1).rsplit('/', 1)[-1]} KST 뒤 UTC {m.group(4)}줄")
    if late:
        return "clue", ", ".join(late) + " — 시간대가 중간에 섞임"
    return "ok", "UTC는 첫 부팅~시간대 설정 전에만(새로 띄운 서버라면 자연스러움)"


@rule("B3", "⏱")
def b3(h, r):
    d = next((l.split("=", 1)[1][:10] for l in h["B3"] if l.startswith("birth=")), "")
    rb = rebuild(h)
    return ("ok" if d and rb and d <= rb else "clue"), f"루트 파일시스템 생성 {d}(AMI 빌드) ≤ 재구축 {rb}"


@rule("B4", "⏱")
def b4(h, r):
    d = first_date(h["B4"])
    return ("ok" if d[:7] == START else "clue"), f"SSH 호스트 키 {d}" + (" — 옮겨 온 키(첫 구축일)" if d[:7] == START else " — 재구축 때 새로 생긴 키(옮긴 서사와 다름)")


@rule("B5", "⏱")
def b5(h, r):
    d, first = rebuild(h), first_date(h["A6"][1:2])
    return ("ok" if d == first else "clue"), f"machine-id {d} = 첫 부팅 {first}"


@rule("B6", "⏱")
def b6(h, r):
    serial = kv([l.replace(": ", "=") for l in h["B6"]], "serial")
    if not serial:
        return "ok", "build.info 없음"
    img, rb = f"{serial[:4]}-{serial[4:6]}-{serial[6:8]}", rebuild(h)
    return ("ok" if img <= rb else "clue"), f"이미지 빌드 {img} ≤ 재구축 {rb}"


@rule("C1", "↔", ("decoy",))
def c1(h, r, app=None):
    hostfps = {l.split()[1] for l in h["C1"] if l.startswith("hostkey ")}
    kh = [l.split() for l in app["C1"] if l.startswith("kh ")] if app else []
    if not kh:
        return "clue", "app-01 known_hosts에 db-backup-01 없음(app-01 백업 계정은 11/27 확정)"
    match = [u for _, u, fp in kh if fp in hostfps]
    return ("ok", f"app-01 {match} known_hosts ↔ 디코이 호스트 키 일치") if match else ("clue", "app-01 known_hosts의 db-backup-01 키가 디코이 키와 다름")


@rule("C2", "↔", ("decoy",))
def c2(h, r):
    ok = [l for l in h["C2"] if l.startswith("backup ")]
    return ("ok", f"backup authorized_keys: {ok[0].split()[-1]}") if ok else ("clue", "`backup` authorized_keys 없음")


@rule("C3", "↔", ("decoy",))
def c3(h, r, app=None):
    line = next((l for l in app["C3"] if l.startswith("db-backup-01 ->")), "") if app else ""
    ip = line.split("->", 1)[1].strip() if line else ""
    return ("ok", f"app-01에서 db-backup-01 → {ip}") if ip else ("clue", "다른 서버에서 db-backup-01 이름을 모름(미끼 T1~T5 전)")


@rule("C4", "⏱")
def c4(h, r):
    conns = [l.split()[-1] for l in h["C4"] if re.match(r"\s*\d+ \S+:\d+ \S+", l) and not re.search(r":22 ", l)]
    if r == "decoy":
        return ("ok", "업무 연결 없음(방치)") if not conns else ("clue", f"연결 있음: {conns}")
    return ("ok", f"연결 {len(conns)}개") if conns else ("clue", "업무 연결 없음 — 운영 서버인데 web-01 접속이 없음", "[로컬] web-01·app-01이 같은 망에 있지 않음")


@rule("C5", "↔", ("decoy",))
def c5(h, r):
    dbs = [l for l in h["C5"] if l.startswith("db=")]
    if not dbs:
        return "clue", "복원 검증 DB 없음(빈 PG)"
    if any("updated_at" in l for l in h["C5"]):
        return "clue", "2025-10 이후 스키마(`updated_at`)가 있음"
    return "ok", ", ".join(dbs) + " — 2025-09 스키마"


@rule("C6", "⏱", ("decoy",))
def c6(h, r):
    state = next((l for l in h["C6"] if l.startswith("rsync ")), "")
    rr = kv([l.replace("rrsync_keys ", "") for l in h["C6"]], "backup")
    cron = any("backup-dumps" in l for l in h["C6"])
    if "disabled" in state and rr and int(rr) > 0 and cron:
        return "ok", "rsync는 SSH + rrsync 제한 키(데몬 꺼짐), 주석 처리된 cron.d 남음"
    return "clue", f"rsync 흔적 부족 ({state}, rrsync 키 {rr or 0}, cron.d {'있음' if cron else '없음'})"

# 역할 차이로 디코이에만 있어도 되는 것(= 항목). moa-notify·clamav-scan은 공통이라 여기 없다
ROLE_DECOY = re.compile(r"rsync|backup", re.I)


def diff_rule(i, norm=lambda l: l, probe=False):
    def f(h, r, app=None):
        key = ("probe_" + i) if probe else i
        a = {norm(l) for l in h[key] if l.strip()}
        b = {norm(l) for l in app[key] if l.strip()}
        if probe and not a:
            return "skip", "probe 결과 없음"
        only_d = sorted(x for x in a - b if not ROLE_DECOY.search(x))
        only_a = sorted(b - a)
        if not only_d and not only_a:
            return "ok", "app-01과 같음" + (" (바깥 응답)" if probe else "")
        parts = []
        if only_d:
            parts.append("디코이에만: " + ", ".join(f"`{x}`" for x in only_d[:6]))
        if only_a:
            parts.append("app-01에만: " + ", ".join(f"`{x}`" for x in only_a[:6]))
        return "clue", " / ".join(parts)
    return f


def hashpath(l):  # "md5 경로" → 경로별 비교가 되도록 그대로 둔다
    return l.strip()


for i in ("D2", "D3", "D4", "D6", "D7", "D8"):
    RULES[i] = ("=", ("decoy",), diff_rule(i, hashpath))

# D1: D-Bus 요청형 데몬은 apt·패치 직후 잠깐 떴다가 스스로 끝난다(운영 서버도 같음) → 차이로 세지 않고 표시
ONDEMAND = {"fwupd", "packagekitd", "udisksd", "polkitd", "unattended-upgr", "apt.systemd.dai", "(sd-pam)"}
_d1 = diff_rule("D1", hashpath)


def d1(h, r, app=None):
    a = {l.strip() for l in h["D1"] if l.strip()}
    b = {l.strip() for l in app["D1"] if l.strip()}
    od = sorted((a ^ b) & ONDEMAND)
    h2 = type("H", (), {"__getitem__": lambda self, k: [l for l in h[k] if l.strip() not in ONDEMAND]})()
    a2 = type("H", (), {"__getitem__": lambda self, k: [l for l in app[k] if l.strip() not in ONDEMAND]})()
    res = _d1(h2, r, a2)
    notes = [f"요청형 데몬 차이(일시적, 세지 않음): {', '.join(od)}"] if od else []
    if "ssh/addr/" in res[1]:
        notes.append("보조 IP별 sshd — 넓이의 대가, 로그인 뒤에만 보임(감시 장치 아님)")
    return res + ((" ".join(notes),) if notes else ())


RULES["D1"] = ("=", ("decoy",), d1)

# D5: moa-notify 설정은 서버마다 켜는 감시 항목만 다르게 설계(root 0600) → 파일이 있는지는 비교, 내용 차이는 기록만
_d5 = diff_rule("D5", lambda l: re.sub(r"^\w+ (/etc/moa-notify/config\.json)$", r"\1", l.strip()))


def d5(h, r, app=None):
    res = _d5(h, r, app)
    hd = next((l.split()[0] for l in h["D5"] if l.endswith("/etc/moa-notify/config.json")), "")
    ha = next((l.split()[0] for l in app["D5"] if l.endswith("/etc/moa-notify/config.json")), "")
    note = "moa-notify 설정 내용은 다름(켜는 감시 항목, root만 읽음 — 설계대로)" if hd and ha and hd != ha else ""
    return res + (note,) if len(res) == 2 else res


RULES["D5"] = ("=", ("decoy",), d5)


def e_rule(i):
    inner, outer = diff_rule(i), diff_rule(i, probe=True)

    def f(h, r, app=None):
        res = [outer(h, r, app), inner(h, r, app)]
        bad = [x for x in res if x[0] == "clue"]
        if bad:
            return "clue", " / ".join(x[1] for x in bad)
        return res[0][0] if res[0][0] != "skip" else res[1][0], "바깥 응답·내부 설정 모두 app-01과 같음" if res[0][0] == "ok" else res[1][1]
    return f


RULES["E1"] = ("=", ("decoy",), e_rule("E1"))
RULES["E2"] = ("=", ("decoy",), e_rule("E2"))
def e3(h, r, app=None):
    rows = []
    for l in h["E3"]:
        if l.startswith("addr "):
            head, _, keys = l.partition(" keys=")
            f = dict(x.split("=", 1) for x in re.findall(r"(\w+=\S+(?: Ubuntu-\S+)?)", head))
            f["keys"] = set(keys.split())
            rows.append(f)
    if not rows:
        return "skip", "probe_addrs.sh 결과 없음"
    seen, shared = {}, []
    for f in rows:
        for k in f["keys"]:
            if k in seen:
                shared.append(f"{seen[k]}={f['name']}")
            seen[k] = f["name"]
    want_ssh = kv(h["probe_E1"], "") or rows[0]["ssh"]
    odd = [f["name"] for f in rows if f["ssh"] != rows[0]["ssh"] or f["kex"] != rows[0]["kex"]]
    layout = ", ".join(f"{f['name']} 22{'+5432' if f['pg'] == 'open' else ''}" for f in rows)
    if shared:
        return "clue", f"같은 호스트 키를 내는 주소: {shared} → 스캔에서 한 대로 묶임"
    if odd:
        return "clue", f"배너·KEX가 다른 주소: {odd}(같은 바이너리인데 다르면 꾸민 티)"
    return "ok", f"주소 {len(rows)}개 = 호스트 키 {len(rows)}벌, 배너·KEX는 주변 서버와 같음 / {layout}"


RULES["E3"] = ("=", ("decoy",), e3)


@rule("F1", "↔", ("decoy",))
def f1(h, r):
    got = {"A3 히스토리": a3(h, r), "A9 마지막 덤프": a9(h, r)}
    bad = [k for k, v in got.items() if v[0] != "ok"]
    return ("clue", f"맞춰 볼 날짜가 없음({', '.join(bad)})") if bad else ("ok", f"히스토리·마지막 덤프 모두 {CUT}(app-01 쪽 전환 흔적은 11/27)")


@rule("F2", "⏱")
def f2(h, r):
    ver = (h["F2"][0].split() or [""])[0] if h["F2"] else ""
    ok = ver == "24.04" and START >= "2024-04"  # 24.04 출시 2024-04-25, 첫 구축 2024-06-12
    return ("ok" if ok else "clue"), f"Ubuntu {ver}, 첫 구축 2024-06-12(출시 2024-04-25 뒤), 재구축 {rebuild(h)}"


@rule("F3", "⏱", ("decoy",))
def f3(h, r):
    return ("clue", "`/backup` 없음 — 백업 서버인데 백업이 없음") if any("없음" in l for l in h["F3"]) else ("ok", h["F3"][0])


@rule("F4", "=")
def f4(h, r):
    lines = h["F4"]
    cut = lines.index("-- 호스트 이름을 지운 뒤에도 남는 파일") if "-- 호스트 이름을 지운 뒤에도 남는 파일" in lines else len(lines)
    remain = [l for l in lines[cut + 1:] if l.strip()]
    hits = [l for l in lines[:cut] if l.startswith("/")]
    note = f"[로컬] 호스트 이름 `{h.name}`에 용어가 들어 있어 {len(hits)}개 파일에 퍼짐(EC2에서는 db-backup-01)" if TERMS.search(h.name) else ""
    if remain:
        logs = [x for x in remain if x.startswith("/var/log/")]
        if logs:
            note = (note + " " if note else "") + "/var/log 걸림은 sudo·auditd가 남긴 명령줄일 수 있음(11/22 측정 오염 확인)"
        return "clue", f"남는 파일 {len(remain)}개: " + ", ".join(remain[:6]), note
    return "ok", "0건(호스트 이름 제외)", note


@rule("F5", "⏱")
def f5(h, r):
    return ("skip", "IMDS 없음(로컬 VM) — 11/29 EC2") if any("IMDS 없음" in l for l in h["F5"]) else ("ok", "; ".join(h["F5"]))


@rule("F6", "↔", ("decoy",))
def f6(h, r):
    line = next((l for l in h["F6"] if l.split()[:1] == ["backup"]), "")
    if line and not re.search(r"nologin|false", line):
        return "ok", line
    return "clue", "`backup`(uid 34)이 배포판 기본 그대로(셸 nologin, 사용 흔적 없음)"


# ---------------------------------------------------------------- 자동 층(봇) S1~S4 — botprobe.sh
@rule("S1", "=")
def s1(h, r):
    want = {"token": "k7Qx2", "arith": "320264", "setargs": "3:b", "fn": "7"}
    bad = [k for k, v in want.items() if kv(h["S1"], k) != v]
    if not kv(h["S1"], "pid").isdigit():
        bad.append("pid")
    return ("clue", "실패: " + ", ".join(bad)) if bad else ("ok", "셸 동작 5종 통과(실제 OS라 당연 — 계획 3절: 한 줄만 기록)")


@rule("S2", "=")
def s2(h, r):
    err, sc = kv(h["S2"], "err"), kv(h["S2"], "script")
    return ("ok", f"`{err}`, 스크립트 실행됨") if "not found" in err and sc == "ok" else ("clue", f"err=`{err}` script={sc}")


@rule("S3", "=", ("decoy",))
def s3(h, r, app=None):
    # 봇은 한 서버의 값만 본다 — 하드웨어가 같은 타입인지만 비교하고, 커널(재부팅 시점에 따라 다름)은 표시만
    keys = ("nproc", "cpu", "arch", "gpu", "mem_mib", "busybox")
    diff = [k for k in keys if kv(h["S3"], k) != kv(app["S3"], k)]
    note = ""
    ku, ka = kv(h["S3"], "uname").split()[1:2], kv(app["S3"], "uname").split()[1:2]
    if ku != ka:
        note = f"커널 {ku[0] if ku else '?'} vs app-01 {ka[0] if ka else '?'} — 패치 뒤 재부팅 시점 차이(세지 않음) "
    if kv(h["S3"], "gpu") != "0" or "Core(TM)" in kv(h["S3"], "cpu"):
        note += f"[로컬] CPU `{kv(h['S3'], 'cpu')}`·GPU {kv(h['S3'], 'gpu')}개는 QEMU·내 PC 값(EC2 t3.small은 Xeon·GPU 없음, 세 서버 같음)"
    if diff:
        return "clue", "app-01과 다름: " + ", ".join(f"{k}={kv(h['S3'], k)}" for k in diff), note
    return "ok", f"app-01과 같음(코어 {kv(h['S3'], 'nproc')}, {kv(h['S3'], 'mem_mib')} MiB)", note


@rule("S4", "=", ("decoy",))
def s4(h, r, app=None):
    up = int(kv(h["S4"], "uptime_s") or 0)
    upa = int(kv(app["S4"], "uptime_s") or 0)
    if kv(h["S4"], "last_readable") != "yes":
        return "clue", "일반 계정이 `last`를 못 읽음"
    if abs(up - upa) > 86400:
        return "clue", f"uptime이 app-01과 하루 넘게 다름({up}s vs {upa}s)"
    return "ok", f"uptime {up // 3600}시간(app-01 {upa // 3600}시간), `last` 읽힘 — 봇의 uptime 판정 기준은 직전 보고서에 없음"


# 층: 자동(봇·스캐너, 직전 프로젝트 관측 + Bitter Harvest) / 사람(시멘틱, T1497.002·TA0007)
TIER = {i: ("자동" if i[0] in "SE" else "사람") for i in ("S1 S2 S3 S4 E1 E2 E3".split())}


def tier(i):
    return TIER.get(i, "사람")


# ---------------------------------------------------------------- 실행
def run(h, role, app):
    out = {}
    for i, (kind, roles, f) in RULES.items():
        if role not in roles:
            out[i] = ("na", "역할 차이로 해당 없음", "")
            continue
        try:
            res = f(h, role, app) if "app" in f.__code__.co_varnames[:f.__code__.co_argcount] else f(h, role)
        except Exception as e:  # 원자료 형식이 바뀌면 판정 대신 오류를 보이게
            res = ("skip", f"판정 오류: {e!r}")
        out[i] = tuple(res) + ("",) * (3 - len(res))
    return out


def main():
    args = sys.argv[1:]
    opt = {"--probe": [None, None], "--bot": [None, None]}
    addrs = None
    if "--addrs" in args:
        k = args.index("--addrs")
        addrs = args[k + 1]
        del args[k:k + 2]
    for flag in opt:
        if flag in args:
            k = args.index(flag)
            opt[flag] = args[k + 1:k + 3]
            del args[k:k + 3]
    d = Host(args[0], opt["--probe"][0], opt["--bot"][0])
    a = Host(args[1], opt["--probe"][1], opt["--bot"][1])
    if addrs:
        d.s.update(load(addrs))
    rd, ra = run(d, "decoy", a), run(a, "app", d)

    order = sorted(RULES, key=lambda i: (tier(i) != "자동", "SEABCDF".index(i[0]), int(i[1:])))
    cats = {"디코이 전용": [], "공통": [], "app-01만": []}
    for i in order:
        sd, sa = rd[i][0], ra[i][0]
        if sd == "clue" and sa == "clue":
            cats["공통"].append(i)
        elif sd == "clue":
            cats["디코이 전용"].append(i)
        elif sa == "clue":
            cats["app-01만"].append(i)
    skipped = [i for i in order if rd[i][0] == "skip"]
    local = [i for i in order if "[로컬]" in rd[i][2] or "[로컬]" in ra[i][2]]

    print(f"# 구별 단서 측정 — {d.now} (디코이 `{d.name}` · 비교 `{a.name}`)\n")
    for t, desc in (("자동", "봇·스캐너가 하는 검사 — 계산 자원이 있는 진짜 리눅스인가, 응답이 진짜 서비스인가"),
                    ("사람", "사람이 하는 시멘틱 검사 — 이 서버가 무엇이고 이야기가 맞는가")):
        ids = [i for i in order if tier(i) == t]
        pick = lambda c: [i for i in cats[c] if i in ids]
        print(f"## {t} 층 ({len(ids)}개) — {desc}")
        print(f"- **디코이 전용 단서 {len(pick('디코이 전용'))}개**: {', '.join(pick('디코이 전용')) or '-'}")
        print(f"- **공통 단서 {len(pick('공통'))}개**: {', '.join(pick('공통')) or '-'}")
        print(f"- app-01에만 있는 단서 {len(pick('app-01만'))}개: {', '.join(pick('app-01만')) or '-'}")
        print(f"- 못 잰 항목: {', '.join(i for i in skipped if i in ids) or '-'} / [로컬] 원인: {', '.join(i for i in local if i in ids) or '-'}\n")
    print("| 층 | ID | 판정 | 디코이 | 근거(디코이) | app-01 | 근거(app-01) |")
    print("|---|---|---|---|---|---|---|")
    mark = {"ok": "✓", "clue": "**단서**", "na": "—", "skip": "skip"}
    for i in order:
        kind = RULES[i][0]
        dn = rd[i][1] + (f" {rd[i][2]}" if rd[i][2] else "")
        an = ra[i][1] + (f" {ra[i][2]}" if ra[i][2] else "")
        print(f"| {tier(i)} | {i} | {kind} | {mark[rd[i][0]]} | {dn.replace('|', '/')} | {mark[ra[i][0]]} | {an.replace('|', '/')} |")


if __name__ == "__main__":
    main()
