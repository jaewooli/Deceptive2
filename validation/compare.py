#!/usr/bin/env python3
"""구별 단서 판정 (checks.md 43개, 자동 층·사람 층). collect.sh·probe.sh·botprobe.sh 원자료를 받아 항목별로 판정한다.
  python3 -I validation/compare.py <디코이.txt> <app.txt> [--probe <디코이.probe> <app.probe>] [--bot <디코이.bot> <app.bot>] > report.md

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

START, CUT = "2024-03", "2025-09"          # 서사: 운영 시작 → S3 전환(이후 방치)
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


@rule("A1", "⏱")
def a1(h, r):
    rotated = any("/var/log/wtmp.1" in l for l in h["A1"])
    begins = next((l for l in h["A1"] if l.startswith("wtmp begins")), "")
    return ("ok", "wtmp 회전 1회 이상") if rotated else ("clue", f"wtmp 회전 0회 — 켠 지 한 달 안({begins})")


@rule("A2", "⏱", ("decoy",))
def a2(h, r):
    line = next((l for l in h["A2"] if l.split()[:1] == ["backup"]), "")
    if not line:
        return "clue", "`backup` 로그인 기록 없음"
    return ("ok", line.strip()) if "2025" in line else ("clue", f"날짜가 서사와 다름: {line.strip()}")


@rule("A3", "⏱", ("decoy",))
def a3(h, r):
    line = next((l for l in h["A3"] if l.startswith("backup ")), "")
    if not line or "없음" in line:
        return "clue", "`backup` 히스토리 없음(root·ubuntu도 없음)" if all("없음" in l for l in h["A3"] if not l.startswith("  ")) else "`backup` 히스토리 없음"
    return "ok", line


@rule("A4", "⏱")
def a4(h, r):
    bad = []
    month = h.now.strftime("%Y-%m")
    for l in h["A4"]:
        parts = l.split()
        if len(parts) < 2:
            continue
        cnt = {p.rsplit(":", 1)[0]: int(p.rsplit(":", 1)[1]) for p in parts[1:]}
        tot = sum(cnt.values())
        if tot and cnt.get(month, 0) / tot > 0.5:
            bad.append(f"{parts[0]} {cnt.get(month, 0)}/{tot}개가 {month}")
    return ("clue", "; ".join(bad) + " — 하루·한 달에 몰림") if bad else ("ok", "기간에 퍼져 있음")


@rule("A5", "⏱")
def a5(h, r):
    n = int(kv(h["A5"], "full_sets") or 0)
    return ("ok", f".4.gz {n}개") if n else ("clue", f"꽉 찬 회전 세트(.4.gz) 0개, 회전 파일 {kv(h['A5'], 'rotated_files')}개 — weekly·rotate 4 기준 한 달 안")


@rule("A6", "⏱")
def a6(h, r):
    first = first_date(h["A6"][1:2])
    boots = kv(h["A6"], "boots")
    if first and date.fromisoformat(first) < h.now - timedelta(days=30):
        return "ok", f"첫 부팅 {first}, {boots}회"
    return "clue", f"저널 첫 부팅 {first}(부팅 {boots}회) — 30일 안"


@rule("A7", "⏱")
def a7(h, r):
    first, runs = kv(h["A7"], "apt_first"), kv(h["A7"], "apt_runs")
    if first and date.fromisoformat(first) <= h.now - timedelta(days=180):
        return "ok", f"apt 이력 {first}부터 {runs}회"
    return "clue", f"apt 이력 {first}~{kv(h['A7'], 'apt_last')} {runs}회, unattended 로그 {kv(h['A7'], 'unattended_runs')}개 — 이미지 빌드일부터 시작"


@rule("A8", "⏱")
def a8(h, r):
    reboots = sum(1 for l in h["A8"] if l.startswith("reboot"))
    boots = int(kv(h["A6"], "boots") or 0)
    rotated = any("/var/log/wtmp.1" in l for l in h["A1"])
    if reboots == boots or rotated:
        return "ok", f"wtmp 재부팅 {reboots}회 = 저널 부팅 {boots}회"
    return "clue", f"wtmp 재부팅 {reboots}회 ≠ 저널 부팅 {boots}회"


@rule("A9", "⏱", ("decoy",))
def a9(h, r):
    if any("없음" in l for l in h["A9"]):
        return "clue", "`/backup/dumps` 없음"
    rows = [l for l in h["A9"] if re.match(r"\d{4}-\d{2}-\d{2} \d+ ", l)]
    first, last = (rows[0][:10], rows[-1][:10]) if rows else ("", "")
    ok = first[:7] == START and last[:7] == CUT
    return ("ok" if ok else "clue"), f"{kv(h['A9'], 'count')}개 {first}~{last}"


@rule("A10", "⏱", ("decoy",))
def a10(h, r):
    n = int(kv(h["A10"], "rsync_lines") or 0)
    return ("ok", f"rsync 기록 {n}줄") if n else ("clue", "rsync 수신 기록 없음")


@rule("B1", "⏱")
def b1(h, r):
    d = first_date(h["B1"])
    inst = sum(1 for l in h["B1"] if l.startswith("d"))
    note = f"[로컬] cloud-init 인스턴스 {inst}개 — vm.sh가 켤 때마다 instance-id를 새로 만듦(11/22 고침)" if inst > 1 else ""
    return ("clue" if after_cut(d) else "ok"), f"cloud-init 로그 {d}", note


@rule("B2", "⏱")
def b2(h, r):
    mixed = []
    for l in h["B2"]:
        m = re.match(r"(\S+) utc=(\d+) kst=(\d+)", l)
        if m and int(m.group(2)) and int(m.group(3)):
            mixed.append(f"{m.group(1).rsplit('/', 1)[-1]} UTC {m.group(2)}줄·KST {m.group(3)}줄")
    return ("clue", ", ".join(mixed) + " — 첫 부팅~base 설치 전 줄이 UTC") if mixed else ("ok", "한 시간대")


@rule("B3", "⏱")
def b3(h, r):
    d = next((l.split("=", 1)[1][:10] for l in h["B3"] if l.startswith("birth=")), "")
    return ("clue" if after_cut(d) else "ok"), f"루트 파일시스템 생성 {d}"


@rule("B4", "⏱")
def b4(h, r):
    d = first_date(h["B4"])
    return ("clue" if after_cut(d) else "ok"), f"SSH 호스트 키 {d}"


@rule("B5", "⏱")
def b5(h, r):
    d = first_date(h["B5"])
    return ("clue" if after_cut(d) else "ok"), f"machine-id·hostname {d}"


@rule("B6", "⏱")
def b6(h, r):
    serial = kv([l.replace(": ", "=") for l in h["B6"]], "serial")
    d = f"{serial[:4]}-{serial[4:6]}-{serial[6:8]}" if serial else ""
    if not serial:
        return "ok", "build.info 없음"
    return ("clue" if d[:7] > START else "ok"), f"이미지 빌드 serial {serial}"


@rule("C1", "↔", ("decoy",))
def c1(h, r, app=None):
    login = any(re.search(r"\bbackup\b", l) for l in h["C1"] if not l.startswith("--"))
    kh = any("known_hosts" in l for l in app["C1"]) if app else False
    if login and kh:
        return "ok", "디코이 backup 로그인 ↔ app-01 known_hosts"
    miss = [x for x, ok in (("디코이 auth.log의 backup 로그인", login), ("app-01 known_hosts", kh)) if not ok]
    return "clue", " · ".join(miss) + " 없음"


@rule("C2", "↔", ("decoy",))
def c2(h, r):
    ok = any(l.startswith("backup ") for l in h["C2"])
    return ("ok", "backup authorized_keys 있음") if ok else ("clue", "`backup` authorized_keys 없음")


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
    return "ok", ", ".join(dbs)


@rule("C6", "⏱", ("decoy",))
def c6(h, r):
    conf = not any("없음" in l for l in h["C6"] if "rsyncd.conf" in l)
    state = next((l for l in h["C6"] if l.startswith("rsync ")), "")
    if conf and "disabled" in state:
        return "ok", f"rsyncd.conf 있음, {state}"
    return "clue", ("rsyncd.conf 없음" if not conf else "rsync가 켜져 있음") + f" ({state})"


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
    return res + ((f"요청형 데몬 차이(일시적, 세지 않음): {', '.join(od)}",) if od else ())


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
RULES["E3"] = ("=", ("decoy",), lambda h, r: ("skip", "11/24 단일 호스트 다중 주소 이후"))


@rule("F1", "↔", ("decoy",))
def f1(h, r):
    got = {"A2": a2(h, r), "A9": a9(h, r), "A10": a10(h, r)}
    missing = [k for k, v in got.items() if v[0] != "ok"]
    return ("clue", f"맞춰 볼 날짜가 없음({', '.join(missing)})") if missing else ("ok", "모두 2025-09")


@rule("F2", "⏱")
def f2(h, r):
    ver = (h["F2"][0].split() or [""])[0] if h["F2"] else ""
    upgraded = not any("기록 없음" in l for l in h["F2"])
    if ver == "24.04" and not upgraded:
        return "clue", "Ubuntu 24.04(2024-04 출시)인데 서사 시작은 2024-03, 업그레이드 기록 없음"
    return "ok", f"{ver}, 업그레이드 기록 {'있음' if upgraded else '없음'}"


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
    keys = ("nproc", "cpu", "arch", "uname", "gpu", "mem_mib", "busybox")
    diff = [k for k in keys if kv(h["S3"], k) != kv(app["S3"], k)]
    note = ""
    if kv(h["S3"], "gpu") != "0" or "Core(TM)" in kv(h["S3"], "cpu"):
        note = f"[로컬] CPU `{kv(h['S3'], 'cpu')}`·GPU {kv(h['S3'], 'gpu')}개는 QEMU·내 PC 값(EC2 t3.small은 Xeon·GPU 없음, 세 서버 같음)"
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
    for flag in opt:
        if flag in args:
            k = args.index(flag)
            opt[flag] = args[k + 1:k + 3]
            del args[k:k + 3]
    d = Host(args[0], opt["--probe"][0], opt["--bot"][0])
    a = Host(args[1], opt["--probe"][1], opt["--bot"][1])
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
