#!/usr/bin/env python3
"""침투 체인 상관분석(plan-wbs 3절 4번) — 흩어진 경보를 "공격자 한 명의 이동" 하나로 묶는다. 관리 쪽에서만(서버엔 상관 규칙·미끼 목록 없음)
  python3 forensics/chain.py watch                 # 수신기를 따라가며 체인이 새 고리를 얻을 때마다 "체인" 경보
  python3 forensics/chain.py build [--last N]      # 수신기 전체(또는 마지막 N줄)로 체인을 다시 만들어 출력(재현·시나리오 판정)

체인 = 미끼 고유 ID → 미끼가 있던 호스트(털린 위치) → 디코이 접속 출발 내부 IP → 사용 계정 → 이후 행동
  고리 종류(시간순):
    미끼 열람   회사 서버 감사 경보 중 경로가 미끼 배치 파일인 것(레지스트리 ops 경로) — 출발 서버·로그인 세션(ses)·계정(auid)
    디코이 접촉 디코이 SSH·PG·터널(투영)·트랩·관문 경보 중 출발(client)이 회사 서버인 것 — 실린 값(키 지문·DB 계정·주소) → 미끼 ID → 털린 위치
    디코이 세션 디코이 로그인 세션 기록(명령·만든 파일) — 출발이 회사 서버
    포렌식      출발지 포렌식 사건(P 특정·스냅숏) — 사건의 로그인 세션으로 체인의 출발 세션을 확정
    출발지 행동 체인의 출발 세션(ses)이 같은 회사 서버에서 낸 다른 감사 경보(지속성·자격증명 열람)
  묶는 규칙: 출발 서버 + 로그인 세션이 같으면 같은 체인. 세션을 모르는 경보(디코이 접촉은 출발 IP만 앎)는
    같은 출발 서버에서 window_seconds 안에 활동한 가장 최근 체인에, 없으면 새 체인. 관리 망·외부 출발은 체인을 안 만듦(기록만)
  체인 경보는 디코이 접촉이 하나라도 있을 때부터(미끼 열람만 있는 체인은 "조기 경보"로만 보관 — 미끼 열람 자체 경보는 이미 감)
결과: out/chains/<체인 ID>.json, 수신기에 source "체인"
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra" / "checks"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

OUT = ROOT / "out" / "chains"
FOR = ROOT / "out" / "forensics"
SINK = Path(os.path.expanduser("~/.cache/deceptive2-vm/webhook.jsonl"))
CONF = yaml.safe_load((Path(__file__).parent / "config.yml").read_text(encoding="utf-8"))
ADDR = re.compile(r"(\d+\.\d+\.\d+\.\d+)(?::(\d+))?")
DECOY_SOURCES = {"sshd", "postgresql", "터널", "포트", "관문"}
NO_SES = {"", None, "4294967295", "unset"}


def ts_of(alert, rec=None):
    for v in (alert.get("log_ts"), (rec or {}).get("received_at")):
        try:
            return datetime.fromisoformat(v).timestamp()
        except (TypeError, ValueError):
            pass
    return time.time()


class Ctx:
    """레지스트리·회사 서버 주소·이름. 시험에선 직접 채운다"""

    def __init__(self, reg, ip2host, name2host):
        self.reg, self.ip2host, self.name2host = reg, ip2host, name2host
        self.bait_files = {}   # 경로 → [배치 ID]
        for pid, p in reg["placements"].items():
            for o in p.get("ops", []):
                path = o.get("path") if isinstance(o, dict) else None
                if path and path not in ("/etc/hosts",) and not o.get("kind", "").startswith("dir"):
                    self.bait_files.setdefault(path, []).append(pid)

    def is_collector(self, host, *pids):
        f = FOR / "collectors.jsonl"
        try:
            st = f.stat().st_size
        except OSError:
            return False
        if st != getattr(self, "_coll_size", None):
            self._coll = set()
            for line in f.read_text().splitlines():
                try:
                    r = json.loads(line)
                    self._coll.add((r["host"], r["pid"]))
                except (ValueError, KeyError):
                    pass
            self._coll_size = st
        return any((host, str(p)) in self._coll for p in pids if p)

    @classmethod
    def load(cls):
        import paths
        v, _ = paths.variables()
        inv = yaml.safe_load((ROOT / "out" / "baits" / "inventory.yml").read_text())["all"]["children"]
        company = set(inv.get("company", {}).get("hosts", {}))
        ip2host = {val: k[3:] for k, val in v.items() if k.startswith("ip:") and k[3:] in company}
        name2host = {h: h for h in company}
        for h in company:
            f = ROOT / "out" / "baits" / "context" / f"{h}.json"
            if f.exists():
                name2host[json.loads(f.read_text()).get("hostname", h)] = h
        reg = json.loads((ROOT / "out" / "baits" / "registry.json").read_text())
        return cls(reg, ip2host, name2host)

    def bait(self, pid):
        p = self.reg["placements"][pid]
        return {"id": pid, "type": p["type"], "host": p["host"], "where": p["anchor_key"], "status": p["status"],
                "value": p["ident"].get("value") if p["ident"].get("kind") not in ("via",) else None}


def classify(alert, ctx):
    """경보 하나 → (고리 종류, 출발 서버, 세션, 내용) 또는 None"""
    src = alert.get("source")
    if src in (None, "체인"):
        return None
    if src == "감사":
        host = ctx.name2host.get(alert.get("host"))
        a = alert.get("audit") or {}
        if not host:
            return None
        if ctx.is_collector(host, a.get("pid"), a.get("ppid")):
            return None   # 출발지 포렌식 수집기 자신(사후 복원 때 ssh config·hosts를 읽음, 11/26 실측)
        ses = a.get("ses") if a.get("ses") not in NO_SES else None
        hits = sorted({pid for path in a.get("paths") or [] for pid in ctx.bait_files.get(path, [])})
        live = [p for p in hits if ctx.reg["placements"][p]["status"] in ("active", "paused")]
        hits = live or hits   # 같은 자리에 다시 배치된 미끼가 여럿이면 지금 것만 — 없을 때만 옛 것(교체 전 유출)
        info = {"user": a.get("auid"), "uid": a.get("uid"), "pid": a.get("pid"), "exe": a.get("exe"), "cmd": a.get("cmd"),
                "result": alert.get("result"), "key": a.get("key")}
        if hits:
            return "미끼 열람", host, ses, dict(info, baits=[ctx.bait(p) for p in hits])
        return "출발지 행동", host, ses, info   # 체인의 세션과 같을 때만 붙음
    if src == "포렌식":
        cid = alert.get("case")
        if not cid:
            return None
        try:
            c = json.loads((FOR / cid / "case.json").read_text())
        except (OSError, ValueError):
            c = {}
        pk = c.get("p_key") or []
        ses = pk[2] if len(pk) == 3 and pk[1] == "ses" else None
        m = re.search(r"사용자 (\S+)", c.get("summary") or alert.get("result") or "")
        return "포렌식", ctx.name2host.get(alert.get("host"), alert.get("host")), ses, \
            {"case": cid, "merged_into": c.get("merged_into"), "summary": c.get("summary") or alert.get("result"),
             "user": m.group(1) if m else None, "alert_line": c.get("alert_line"), "p_seconds": c.get("alert_to_p_seconds")}
    m = ADDR.search(alert.get("client") or "")
    origin = ctx.ip2host.get(m.group(1)) if m else None
    if not origin:
        return None   # 관리 망·디코이·외부 출발 — 체인 안 만듦
    if src == "세션":
        s = alert.get("session") or {}
        return "디코이 세션", origin, None, {"decoy": alert.get("host"), "user": alert.get("user"), "end": s.get("end"),
                                           "commands": [" ".join(c.get("argv") or [])[:200] for c in s.get("commands", [])],
                                           "files": [{k: f.get(k) for k in ("path", "size", "sha256", "error")} for f in s.get("files", [])],
                                           "collector": alert.get("collector")}
    if src in DECOY_SOURCES:
        from correlate import bait_of
        baits = [ctx.bait(b["placement"]) for b in bait_of(alert, ctx.reg)]
        return "디코이 접촉", origin, None, {"decoy": decoy_label(alert), "via": src, "user": alert.get("user"),
                                           "result": alert.get("result"), "baits": baits}
    return None


def decoy_label(alert):
    """경보 낸 장치 → 공격자가 닿은 "서버" 이름: 투영은 팜이 알려 주므로 결과 글의 디코이 이름, 트랩은 회사 서버의 빈 포트"""
    r = alert.get("result") or ""
    if alert.get("source") == "터널":
        m = re.match(r"(\S+?)\(", r)
        return m.group(1) if m else alert.get("host")
    if alert.get("source") == "포트":
        m = re.search(r":(\d+)", r)
        return f"{alert.get('host')}:{m.group(1) if m else '?'} 트랩"
    return alert.get("host")


class Chains:
    def __init__(self, ctx, window=None):
        self.ctx = ctx
        self.window = float(window or CONF.get("chain_window_seconds", 1800))
        self.chains = {}   # ID → 체인
        self.by_line = {}  # 수신기 줄 → 체인 ID(포렌식 사건의 alert_line으로 붙이기)
        self.n = 0

    def _new(self, origin, ses, t):
        self.n += 1
        cid = datetime.fromtimestamp(t).strftime("%Y%m%d-%H%M%S-") + f"{self.n:03d}-{origin}"
        self.chains[cid] = {"id": cid, "origin": origin, "ses": ses, "start": t, "last": t, "links": []}
        return self.chains[cid]

    def _find(self, origin, ses, t, line_hint=None):
        if line_hint and line_hint in self.by_line:
            return self.chains[self.by_line[line_hint]]
        live = [c for c in self.chains.values() if c["origin"] == origin and t - c["last"] <= self.window]
        if ses:
            same = [c for c in live if c["ses"] == ses]
            if same:
                return same[-1]
            live = [c for c in live if c["ses"] is None]   # 세션 모르는 체인에 세션을 줌
        return max(live, key=lambda c: c["last"]) if live else None

    def _move(self, line, dst):
        """수신기 줄 line의 고리를 체인 dst로(포렌식이 그 접촉의 진짜 출발 세션을 알려 줬을 때). 빈 체인은 지움"""
        src = self.chains.get(self.by_line.get(line))
        if not src or src is dst:
            return
        moved = [l for l in src["links"] if l["line"] == line]
        src["links"] = [l for l in src["links"] if l["line"] != line]
        dst["links"] = sorted(dst["links"] + moved, key=lambda l: l["ts"])
        for l in moved:
            dst["last"] = max(dst["last"], datetime.fromisoformat(l["ts"]).timestamp())
        self.by_line[line] = dst["id"]
        if not src["links"]:
            del self.chains[src["id"]]

    def add(self, alert, line_no, rec=None):
        r = classify(alert, self.ctx)
        if not r:
            return None
        kind, origin, ses, info = r
        t = ts_of(alert, rec)
        hint = info.get("alert_line") if kind == "포렌식" else None
        c = self._find(origin, ses, t, hint)
        if kind == "포렌식" and c is not None and ses and c["ses"] not in (None, ses):
            # 사건이 가리킨 접촉은 다른 로그인 세션이 한 것 — 그 세션의 체인으로 옮긴다(없으면 새 체인)
            dst = next((x for x in self.chains.values() if x["origin"] == origin and x["ses"] == ses and t - x["last"] <= self.window), None) \
                or self._new(origin, ses, t)
            self._move(hint, dst)
            c = dst
        if kind == "출발지 행동" and (c is None or not ses or c["ses"] != ses):
            return None   # 체인의 출발 세션이 한 일만
        if kind == "포렌식" and c is None:
            return None
        if c is None:
            c = self._new(origin, ses, t)
        if ses and not c["ses"]:
            c["ses"] = ses
        c["last"] = max(c["last"], t)
        c["links"].append(dict(info, kind=kind, ts=datetime.fromtimestamp(t).astimezone().isoformat(timespec="milliseconds"),
                               line=line_no, ses=ses))
        self.by_line[line_no] = c["id"]
        return c

    @staticmethod
    def summary(c):
        L = c["links"]
        kinds = [l["kind"] for l in L]
        baits = {}
        for l in L:
            for b in l.get("baits") or []:
                if b["type"] not in ("projection", "decoy_port"):   # 투영·트랩은 목적지(디코이)지 털린 미끼가 아님
                    baits[b["id"]] = b
        acct = next((l["user"] for l in L if l["kind"] in ("미끼 열람", "포렌식") and l.get("user") not in (None, "unset")), None)
        decoys = []
        for l in L:
            if l["kind"] in ("디코이 접촉", "디코이 세션") and l["decoy"] not in decoys:
                decoys.append(l["decoy"])
        dusers = sorted({l["user"] for l in L if l["kind"] in ("디코이 접촉", "디코이 세션") and l.get("user")})
        cmds = [x for l in L if l["kind"] == "디코이 세션" for x in l["commands"]]
        files = [f for l in L if l["kind"] == "디코이 세션" for f in l["files"]]
        cases = sorted({l.get("merged_into") or l["case"] for l in L if l["kind"] == "포렌식"})
        later = [l for l in L if l["kind"] == "출발지 행동"]
        where = ", ".join(f"{b['id']} {b['type']}@{b['host']}({b['where'].split(':', 2)[-1]})" for b in baits.values()) or "미끼 모름"
        s = (f"{c['origin']}" + (f"({acct}" + (f", 세션 {c['ses']}" if c["ses"] else "") + ")" if acct or c["ses"] else "")
             + f" · 털린 미끼 {where} → {' → '.join(decoys) or '디코이 접촉 없음'}"
             + (f"({', '.join(dusers)})" if dusers else "")
             + (f" · 디코이 명령 {len(cmds)}개·파일 {len(files)}개" if cmds or files else "")
             + (f" · 포렌식 {', '.join(cases)}" if cases else "")
             + (f" · 출발지 행동 {len(later)}건" if later else ""))
        return {"text": s, "kinds": sorted(set(kinds)), "baits": list(baits.values()), "decoys": decoys, "decoy_users": dusers,
                "account": acct, "commands": cmds, "files": files, "cases": cases, "confirmed": "디코이 접촉" in kinds or "디코이 세션" in kinds}


def post(body):
    url = CONF.get("sink_url")
    if not url:
        return
    try:
        urllib.request.urlopen(urllib.request.Request(url, json.dumps(body, ensure_ascii=False).encode(),
                                                      {"Content-Type": "application/json"}), timeout=5)
    except Exception as e:
        print("! 수신기 전송 실패:", e, file=sys.stderr)


def save(c):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{c['id']}.json").write_text(json.dumps(dict(c, summary=Chains.summary(c)), ensure_ascii=False, indent=1))


def signature(c):
    s = Chains.summary(c)
    return (tuple(s["kinds"]), tuple(b["id"] for b in s["baits"]), tuple(s["decoys"]), len(s["commands"]), len(s["files"]), tuple(s["cases"]))


def records(lines, start=1):
    for n, line in enumerate(lines, start):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        yield n, rec, rec.get("body") or {}


def cmd_build(a):
    lines = SINK.read_text(encoding="utf-8").splitlines()
    start = max(1, len(lines) - a.last + 1) if a.last else 1
    ch = Chains(Ctx.load())
    for n, rec, alert in records(lines[start - 1:], start):
        ch.add(alert, n, rec)
    for c in ch.chains.values():
        s = Chains.summary(c)
        if s["confirmed"] or a.all:
            save(c)
            print(f"[{c['id']}] {'체인' if s['confirmed'] else '조기(미끼 열람만)'} {s['text']}")
            for l in c["links"]:
                print(f"    {l['ts'][11:23]} {l['kind']:6} {(l.get('decoy') or '')} {(l.get('result') or l.get('summary') or ' | '.join(l.get('commands') or []))[:110]}")


def cmd_watch(a):
    ch = Chains(Ctx.load())
    sent = {}
    print(f"체인 상관분석: {SINK} 따라가기")
    with open(SINK, encoding="utf-8") as f:
        n = sum(1 for _ in open(SINK, encoding="utf-8"))
        f.seek(0, 2)
        loaded = time.monotonic()
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.2)
                continue
            n += 1
            if time.monotonic() - loaded > 30:   # 레지스트리(미끼 교체)가 바뀌었을 수 있음
                ch.ctx, loaded = Ctx.load(), time.monotonic()
            for _, rec, alert in records([line], n):
                c = ch.add(alert, n, rec)
                if not c:
                    continue
                s = Chains.summary(c)
                sig = signature(c)
                save(c)
                if s["confirmed"] and sent.get(c["id"]) != sig:
                    first = c["id"] not in sent
                    sent[c["id"]] = sig
                    post({"host": "관리", "source": "체인", "client": c["origin"], "user": s["account"], "database": None,
                          "result": f"[{c['id']}] {'새 체인' if first else '체인 갱신'} — {s['text']}"[:800],
                          "log_ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                          "chain": {"id": c["id"], "origin": c["origin"], "ses": c["ses"], "baits": s["baits"], "decoys": s["decoys"],
                                    "decoy_users": s["decoy_users"], "cases": s["cases"], "links": len(c["links"])}})
                    print(f"{'▶' if first else '·'} [{c['id']}] {s['text']}")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(required=True)
    sp.add_parser("watch").set_defaults(f=cmd_watch)
    b = sp.add_parser("build")
    b.add_argument("--last", type=int, default=0)
    b.add_argument("--all", action="store_true", help="미끼 열람만 있는 조기 체인도")
    b.set_defaults(f=cmd_build)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
