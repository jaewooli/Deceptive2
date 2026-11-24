#!/usr/bin/env python3
"""출발지 포렌식 — Illusive(US10382484) "트랩에 접속한 출발 컴퓨터 A에서, 트랩에 접속 중인 프로세스 P를 찾아 P의 활동을 기록"을 관리 쪽에서.
  python3 forensics/correlate.py watch            # 수신기(webhook.jsonl)를 따라가며 경보마다 수집(기술 스위치 forensics가 켜져 있을 때)
  python3 forensics/correlate.py once <줄 번호>    # 수신기의 그 줄 경보 하나로(시험·재현)
  python3 forensics/correlate.py show <사건 ID>    # 사건 요약

경보 → 출발지 정하기(관리 쪽, 서버엔 상관 규칙 없음):
  - 디코이·트랩·투영·관문 경보: client IP가 회사 서버면 그 서버, 출발 소켓 = client IP:포트 → 수집기가 그 소켓의 주인 프로세스 = P
  - 미끼 열람(감사) 경보: 출발지 = 경보 낸 서버 자신, P = 감사 기록의 pid(벤더보다 이른 시점 — 디코이에 가기 전)
  - 회사 서버가 아닌 출발지(관리 망·디코이·외부)는 수집 안 함(기록만)
수집기 forensics/collect.py와 인자는 표준입력으로 보냄(서버에 파일 안 남김, ps엔 `python3 -`만). 전달은 환경 프로필 access.run_py(로컬 SSH, AWS SSM Run Command 11/29)
결과: out/forensics/<사건>/ (alert.json, collect.jsonl, case.json) + 수신기에 "포렌식" 경보 두 번(P 특정 즉시, 추적 끝)
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra" / "checks"))
import paths  # noqa: E402

import yaml  # noqa: E402

OUT = ROOT / "out" / "forensics"
SINK = Path(os.path.expanduser("~/.cache/deceptive2-vm/webhook.jsonl"))
CONF = yaml.safe_load((Path(__file__).parent / "config.yml").read_text(encoding="utf-8"))
ADDR = re.compile(r"(\d+\.\d+\.\d+\.\d+)(?::(\d+))?")


def now():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def env():
    v, dest = paths.variables()
    paths.VARS = v
    company = set(yaml.safe_load((ROOT / "out" / "baits" / "inventory.yml").read_text())["all"]["children"]
                  .get("company", {}).get("hosts", {}))
    ip2host = {val: k[3:] for k, val in v.items() if k.startswith("ip:") and k[3:] in company}
    name2host = {}
    for h in company:
        f = ROOT / "out" / "baits" / "context" / f"{h}.json"
        name2host[h] = h
        if f.exists():
            name2host[json.loads(f.read_text()).get("hostname", h)] = h
    reg = json.loads((ROOT / "out" / "baits" / "registry.json").read_text())
    return v, dest, ip2host, name2host, reg


def feature_on(reg):
    return reg.get("features", {}).get("forensics", "on") == "on"


def bait_of(alert, reg):
    """경보에 실린 미끼 고유 값(키 지문·DB 계정·트랩/투영 주소) → 레지스트리 배치(active·paused·retired 모두)"""
    hay = " ".join(str(alert.get(k) or "") for k in ("result", "user", "client"))
    hits = []
    for pid, p in reg["placements"].items():
        kind, val = p["ident"].get("kind"), str(p["ident"].get("value", ""))
        if not val:
            continue
        hit = (kind in ("ssh_key", "aws_key") and val in hay) or (kind == "db_user" and alert.get("user") == val) or \
              (kind == "projection" and val.split("@")[0] + "(" in hay)
        if hit:
            hits.append({"placement": pid, "type": p["type"], "host": p["host"], "status": p["status"], "anchor": p["anchor_key"]})
    # 같은 값의 배치가 여럿(다시 배치된 투영 디코이 등)이면 지금 살아 있는 것만 — 없을 때만 옛 것 전부(교체 전 유출 추적)
    live = [h for h in hits if h["status"] in ("active", "paused")]
    return live or hits


def decide(alert, ip2host, name2host):
    """(출발 서버, 수집기 인자, 이유) 또는 (None, None, 이유)"""
    src = alert.get("source")
    if src == "포렌식":
        return None, None, "자기 경보"
    if src == "감사":
        a = alert.get("audit") or {}
        exe = a.get("exe") or ""
        for rule in CONF["audit_skip"]:
            if re.search(rule["exe"], exe) and (a.get("auid") or "unset") == rule.get("auid", a.get("auid")):
                return None, None, f"억제 목록 exe({exe}, auid {a.get('auid')}) — 11/30 오탐 분석 대상"
        host = name2host.get(alert.get("host"))
        if not host:
            return None, None, f"회사 서버 아님({alert.get('host')})"
        if not a.get("pid"):
            return None, None, "감사 기록에 pid 없음"
        return host, ["pid", ",".join(x for x in (a.get("pid"), a.get("ppid")) if x), a.get("ses") or ""], \
            "미끼 열람 — 출발지 = 그 서버(P가 끝났으면 부모, 그것도 없으면 같은 로그인 세션)"
    m = ADDR.search(alert.get("client") or "")
    if not m:
        return None, None, "출발 주소 없음"
    ip, port = m.group(1), m.group(2)
    host = ip2host.get(ip)
    if not host:
        return None, None, f"출발 {ip}는 회사 서버가 아님(관리 망·디코이·외부) — 수집 안 함"
    if not port:
        return host, None, "출발 포트 없음(ICMP 등) — 스냅숏만"
    return host, ["sock", ip, port], "디코이 접속 — 출발 소켓의 주인"


class Cases:
    """같은 출발(서버, 출발 소켓 또는 pid)은 추적 중이면 다시 수집하지 않고 그 사건에 경보를 붙인다"""

    def __init__(self):
        self.live = {}
        self.own = {}   # 서버 → 수집기 pid(자기 수집이 만든 감사 경보 무시)
        self.by_p = {}  # (서버, P pid) → 사건 ID — 경보 둘(미끼 열람 + 디코이 접속)이 같은 P를 가리키면 한 사건으로
        self.lock = threading.Lock()
        self.n = 0

    def key(self, host, args):
        return (host, tuple(args or ()))


CASES = Cases()


def post(body, dest):
    url = (dest.get("notify") or {}).get("collector_url") or CONF.get("sink_url")
    if not url:
        return
    try:
        urllib.request.urlopen(urllib.request.Request(url, json.dumps(body, ensure_ascii=False).encode(),
                                                      {"Content-Type": "application/json"}), timeout=5)
    except Exception as e:
        print("! 수신기 전송 실패:", e, file=sys.stderr)


def summarize(target):
    c = target.get("chain") or []
    if not c:
        return "P 못 찾음(연결·프로세스가 이미 끝남)"
    p = c[0]
    tree = " ← ".join(f"{x['comm']}[{x['pid']}]" for x in c[:6])
    s = f"P={p['comm']}[{p['pid']}] 사용자 {p['user']} 실행 {' '.join(p['cmd'])[:120]} | {tree}"
    if target.get("ssh_connection"):
        s += f" | 앞 홉 SSH_CONNECTION={target['ssh_connection']}"
    return s


def run_case(alert, line_no, host, args, why, v, dest, reg, recv_epoch=None):
    with CASES.lock:
        CASES.n += 1
        cid = datetime.now().strftime("%Y%m%d-%H%M%S-") + f"{CASES.n:03d}-{host}"
    d = OUT / cid
    d.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    case = {"id": cid, "alert_line": line_no, "alert": alert, "source_host": host, "why": why, "args": args,
            "baits": bait_of(alert, reg), "started": now(), "follow_seconds": CONF["follow_seconds"]}
    (d / "alert.json").write_text(json.dumps(alert, ensure_ascii=False, indent=1))
    tpl = (dest.get("access") or {}).get("run_py")
    if not tpl:
        sys.exit("환경 프로필 access.run_py 없음")
    a = list(args or ["pid", "1"])
    secs = str(CONF["follow_seconds"] if args else 0)
    a = a[:2] + [secs] + a[2:] if a[0] == "pid" else a + [secs]
    # 인자는 명령줄이 아니라 표준입력으로 — 출발지의 ps에 공격자 자기 pid·포트가 보이면 수집이 들킨다(11/24 공격자 시점 검사)
    cmd = tpl.format(host=shlex.quote(host), root=ROOT, key=dest["access"].get("key", ""))
    code = f"import sys; sys.argv = ['-'] + {a!r}\n".encode() + (Path(__file__).parent / "collect.py").read_bytes()
    pr = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pr.stdin.write(code)
    pr.stdin.close()
    acts = 0
    with open(d / "collect.jsonl", "w") as f:
        for raw in pr.stdout:
            f.write(raw.decode("utf-8", "replace"))
            f.flush()
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            k = rec["kind"]
            if k == "self":
                with CASES.lock:
                    CASES.own.setdefault(host, set()).add(str(rec["pid"]))
            elif k == "target":
                case["target"] = {kk: rec.get(kk) for kk in ("pid", "alive", "anchor", "ssh_connection", "latency")}
                case["p_found_at"] = now()
                case["alert_to_p_seconds"] = round(time.time() - recv_epoch, 3) if recv_epoch else None   # 수신기 시각(호스트 시계 — VM 시계와 다를 수 있음)
                case["summary"] = summarize(rec)
                ses = rec.get("ses") or ""
                pk = (host, "ses", ses) if ses and ses != "4294967295" else (host, "anchor", rec.get("anchor"))
                case["p_key"] = list(pk)
                with CASES.lock:
                    first = CASES.by_p.setdefault(pk, cid) if rec.get("pid") else cid
                if first != cid:   # 이미 같은 P를 추적 중 — 이 수집은 멈추고 그 사건에 경보를 붙임
                    pr.terminate()
                    case["merged_into"] = first
                    m = OUT / first / "merged.jsonl"
                    with open(m, "a") as mf:
                        mf.write(json.dumps({"case": cid, "alert_line": line_no, "alert": alert, "alert_to_p_seconds":
                                             round(time.time() - recv_epoch, 3) if recv_epoch else None},
                                            ensure_ascii=False) + "\n")
                    print(f"[{cid}] 같은 세션·셸을 추적 중 → 사건 {first}에 합침")
                    break
                print(f"[{cid}] {case['summary']}  (경보→P {case['alert_to_p_seconds']}초)")
            elif k == "socket":
                case["socket"] = rec.get("found")
            elif k == "snapshot":
                case["snapshot_took"] = rec.get("took")
                post({"host": host, "source": "포렌식", "client": alert.get("client"), "user": None, "database": None,
                      "result": f"[{cid}] 스냅숏 · {case.get('summary', '')}"[:600], "log_ts": now(), "case": cid,
                      "baits": [b["placement"] for b in case["baits"]]}, dest)
            elif k == "act":
                acts += 1
                if acts <= CONF.get("print_acts", 5):
                    print(f"[{cid}]   활동 {rec.get('src')} {' '.join(rec.get('argv') or [])[:160]}")
    pr.wait()
    if case.get("merged_into"):
        (d / "case.json").write_text(json.dumps(case, ensure_ascii=False, indent=1))
        with CASES.lock:
            CASES.live.pop(CASES.key(host, args), None)
        return case
    err = pr.stderr.read().decode("utf-8", "replace").strip()
    case.update(ended=now(), exit=pr.returncode, activities=acts, took=round(time.time() - t_start, 1))
    if err:
        case["stderr"] = err[-2000:]
    (d / "case.json").write_text(json.dumps(case, ensure_ascii=False, indent=1))
    post({"host": host, "source": "포렌식", "client": alert.get("client"), "user": None, "database": None,
          "result": f"[{cid}] 추적 끝 — 활동 {acts}건, {case['took']}초", "log_ts": now(), "case": cid}, dest)
    with CASES.lock:
        CASES.live.pop(CASES.key(host, args), None)
        if case.get("p_key"):
            CASES.by_p.pop(tuple(case["p_key"]), None)
    return case


def handle(alert, line_no, ctx, threaded=True, recv=None):
    v, dest, ip2host, name2host, reg = ctx
    if alert.get("source") == "감사":
        h = name2host.get(alert.get("host"))
        a = alert.get("audit") or {}
        with CASES.lock:
            mine = CASES.own.get(h, set())
            if a.get("pid") in mine or a.get("ppid") in mine:
                return None
    host, args, why = decide(alert, ip2host, name2host)
    if not host:
        print(f"· {alert.get('host')}/{alert.get('source')} {alert.get('client')}: {why}")
        return None
    k = CASES.key(host, args)
    with CASES.lock:
        if k in CASES.live:
            CASES.live[k].append(line_no)
            print(f"· 추적 중 사건에 붙임: {k}")
            return None
        CASES.live[k] = [line_no]
    print(f"▶ {alert.get('host')}/{alert.get('source')} {alert.get('client')} → 출발지 {host} {args} ({why})")
    if threaded:
        threading.Thread(target=run_case, args=(alert, line_no, host, args, why, v, dest, reg, recv), daemon=True).start()
        return None
    return run_case(alert, line_no, host, args, why, v, dest, reg, recv)


def cmd_watch(a):
    ctx = env()
    print(f"수신기 따라가기: {SINK} (forensics {'켜짐' if feature_on(ctx[4]) else '꺼짐'})")
    with open(SINK, "r", encoding="utf-8") as f:
        f.seek(0, 2)
        n = sum(1 for _ in open(SINK, encoding="utf-8"))
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.2)
                continue
            n += 1
            try:
                rec = json.loads(line)
                alert = rec.get("body") or {}
                recv = datetime.fromisoformat(rec["received_at"]).timestamp()
            except (ValueError, KeyError):
                continue
            ctx = env()   # 레지스트리·스위치가 바뀌었을 수 있음
            if not feature_on(ctx[4]):
                continue
            handle(alert, n, ctx, recv=recv)


def cmd_once(a):
    lines = SINK.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[a.line - 1])
    c = handle(rec["body"], a.line, env(), threaded=False)
    if c:
        print(json.dumps({k: c.get(k) for k in ("id", "summary", "alert_to_p_seconds", "snapshot_took", "activities", "baits")},
                         ensure_ascii=False, indent=1))


def cmd_show(a):
    c = json.loads((OUT / a.case / "case.json").read_text())
    print(json.dumps({k: v for k, v in c.items() if k != "alert"}, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(required=True)
    sp.add_parser("watch").set_defaults(f=cmd_watch)
    o = sp.add_parser("once")
    o.add_argument("line", type=int)
    o.set_defaults(f=cmd_once)
    s = sp.add_parser("show")
    s.add_argument("case")
    s.set_defaults(f=cmd_show)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
