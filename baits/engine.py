#!/usr/bin/env python3
"""미끼 배포 엔진 — Illusive식 맥락 기반 원격 배포(01-vendor-feature-map 문제 1)를 Ansible 위에.
  python3 baits/engine.py collect          서버 맥락 수집(읽기 전용) → out/baits/context/<호스트>.json
  python3 baits/engine.py plan             맥락 + 레지스트리 → 새로 둘 자리 / 맥락이 사라진 자리(회수 후보)
  python3 baits/engine.py apply            plan대로 배치하고 레지스트리에 기록
  python3 baits/engine.py verify           주기 재적용: 사라지거나 바뀐 미끼 = 경보 + 복구(드리프트)
  python3 baits/engine.py rotate [ID|--all] 고유 ID 교체. 옛 ID는 retired로 남겨 계속 감시
  python3 baits/engine.py recall [ID|--host H|--all]  깨끗하게 회수
  python3 baits/engine.py list
레지스트리: out/baits/registry.json(로컬, 커밋 안 함 — 미끼 실제 값이 들어 있음). AWS에선 비공개 S3(11/28)
목적지: out/baits/destinations.yml  {db-backup-01: {ip: ...}}
경보: 환경변수 BAIT_WEBHOOK_URL(없으면 표준 출력)
"""
import argparse
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import bait_types as T  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE.parent / "out" / "baits"
REG = OUT / "registry.json"
ANSIBLE = os.environ.get("ANSIBLE_BIN", str(Path.home() / ".cache/deceptive2-ctl/bin"))


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def load_reg():
    if REG.exists():
        return json.loads(REG.read_text())
    return {"placements": {}, "events": []}


def save_reg(r):
    OUT.mkdir(parents=True, exist_ok=True)
    REG.write_text(json.dumps(r, ensure_ascii=False, indent=1))
    os.chmod(REG, 0o600)


def event(r, kind, pid, **kw):
    e = {"at": now(), "kind": kind, "id": pid, **kw}
    r["events"].append(e)
    return e


def inventory():
    inv = yaml.safe_load((OUT / "inventory.yml").read_text())
    groups = inv["all"]["children"]
    return {g: list(groups[g]["hosts"]) for g in groups}


def ansible_json(args, extra=None):
    env = dict(os.environ, ANSIBLE_STDOUT_CALLBACK="ansible.posix.json", ANSIBLE_CONFIG=str(HERE / "ansible.cfg"))
    p = subprocess.run([f"{ANSIBLE}/{args[0]}", *args[1:]], cwd=HERE, env=env, capture_output=True, text=True)
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        raise SystemExit(f"ansible 실패:\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}")


# ------------------------------------------------------------------ 맥락
def collect():
    hosts = inventory()["company"]
    out = ansible_json(["ansible-playbook", "playbooks/collect.yml", "-l", ",".join(hosts)])
    (OUT / "context").mkdir(parents=True, exist_ok=True)
    got = {}
    for task in out["plays"][0]["tasks"]:
        for h, res in task["hosts"].items():
            if res.get("stdout", "").startswith("{"):
                got[h] = json.loads(res["stdout"])
                (OUT / "context" / f"{h}.json").write_text(json.dumps(got[h], ensure_ascii=False, indent=1))
    print(f"맥락 수집: {', '.join(sorted(got))}")
    return got


def contexts():
    return {p.stem: json.loads(p.read_text()) for p in (OUT / "context").glob("*.json")}


def anchor_key(tname, host, a):
    pick = {"env_db_url": ("path", "key"), "ssh_config": ("user",), "history": ("user",), "aws_profile": ("user",),
            "agent_session": ("user",), "sync_service": ("name",)}[tname]
    return f"{tname}:{host}:" + ":".join(str(a[k]) for k in pick)


# ------------------------------------------------------------------ 계획
def constraints():
    p = HERE / "constraints.yml"
    return {d["anchor"]: d["reason"] for d in (yaml.safe_load(p.read_text()) or {}).get("deny", [])} if p.exists() else {}


def plan(r, ctxs):
    deny = constraints()
    active = {p["anchor_key"]: pid for pid, p in r["placements"].items() if p["status"] == "active"}
    used = {p["ident"]["value"] for p in r["placements"].values()}
    new, seen = [], set()
    for host, ctx in ctxs.items():
        for tname, t in T.TYPES.items():
            for a in t.match(ctx, host):
                key = anchor_key(tname, host, a)
                seen.add(key)
                if key in active:
                    continue
                if key in deny:
                    print(f"막힘    {tname:12} {host:12} {key} — {deny[key]}")
                    continue
                # 히스토리는 같은 사용자에게 SSH 미끼가 있을 때만(길잡이)
                if tname == "history" and not any(k.startswith(f"ssh_config:{host}:{a['user']}") for k in list(active) + [n["anchor_key"] for n in new]):
                    continue
                new.append({"type": tname, "host": host, "anchor": a, "anchor_key": key})
                used.add("_")
    gone = [pid for key, pid in active.items() if key not in seen and r["placements"][pid]["host"] in ctxs]
    return new, gone


def dests():
    p = OUT / "destinations.yml"
    return yaml.safe_load(p.read_text()) if p.exists() else {T.DECOY: {"ip": "10.0.2.30"}}


def build(r, item, rotated_from=None):
    t = T.TYPES[item["type"]]
    used = {p["ident"]["value"] for p in r["placements"].values()}
    dest = dests()[T.DECOY]
    ident = t.new_ident(item["anchor"], used, dest) if "dest" in t.new_ident.__code__.co_varnames else t.new_ident(item["anchor"], used)
    ops = t.ops(item["anchor"], ident, dest)
    pid = secrets.token_hex(4)
    r["placements"][pid] = {"type": item["type"], "host": item["host"], "anchor": item["anchor"], "anchor_key": item["anchor_key"],
                            "ident": ident, "ops": ops, "status": "active", "created": now(), "rotated_from": rotated_from}
    return pid


def split_ops(placements, mode):
    """작업을 실제로 적용할 호스트별로(디코이 쪽 작업은 디코이로)"""
    by, index = {}, {}
    for pid, p in placements:
        for i, op in enumerate(p["ops"]):
            h = op["decoy"] if op["kind"] == "decoy_key" else p["host"]
            index.setdefault(h, []).append((pid, i))
            by.setdefault(h, []).append(op)
    return by, index


def run_ops(placements, mode):
    """출발 서버 작업을 먼저, 성공한 뒤에 디코이 쪽 작업(11/22: 출발 쪽이 실패해도 디코이 키만 쌓이던 문제)"""
    by, index = split_ops(placements, mode)
    decoys = set(inventory().get("decoys", []))
    first = {h: v for h, v in by.items() if h not in decoys}
    second = {h: v for h, v in by.items() if h in decoys}
    states = {}
    for part in (first, second):
        if part:
            for pid, st in _run({h: by[h] for h in part}, {h: index[h] for h in part}, mode).items():
                states.setdefault(pid, []).extend(st)
    return states


def _run(by, index, mode):
    if not by:
        return {}
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f".ops-{secrets.token_hex(3)}.json"
    f.write_text(json.dumps({"ops_by_host": by, "op_mode": mode}))
    os.chmod(f, 0o600)
    try:
        out = ansible_json(["ansible-playbook", "playbooks/apply.yml", "-l", ",".join(by), "-e", f"@{f}"])
    finally:
        f.unlink()
    states = {}
    for task in out["plays"][0]["tasks"]:
        for h, res in task["hosts"].items():
            if res.get("failed") or res.get("unreachable"):
                tail = lambda x: (x or "")[-1500:]
                raise SystemExit(f"{h}: {res.get('msg')}\n--- stderr\n{tail(res.get('stderr'))}\n--- stdout\n{tail(res.get('stdout'))}")
            if res.get("stdout", "").startswith('{"results"'):
                for x in json.loads(res["stdout"])["results"]:
                    pid, i = index[h][x["i"]]
                    states.setdefault(pid, []).append((h, i, x["state"]))
    return states


def alert(e):
    text = f"[미끼 {e['kind']}] {e['id']} {e.get('type','')} {e.get('host','')} {e.get('detail','')}"
    url = os.environ.get("BAIT_WEBHOOK_URL")
    if url:
        body = json.dumps({"content": text}).encode()
        urllib.request.urlopen(urllib.request.Request(url, body, {"Content-Type": "application/json"}), timeout=10)
    print("경보:", text)


# ------------------------------------------------------------------ 명령
def cmd_plan(a):
    r = load_reg()
    new, gone = plan(r, contexts())
    for n in new:
        print(f"새 자리  {n['type']:12} {n['host']:12} {n['anchor_key']}")
    for pid in gone:
        print(f"맥락 사라짐(회수 후보) {pid} {r['placements'][pid]['anchor_key']}")
    if not new and not gone:
        print("바꿀 것 없음")
    return r, new, gone


def cmd_apply(a):
    r, new, gone = cmd_plan(a)
    pids = [build(r, n) for n in new]
    # 서버에 손대기 전에 먼저 기록한다 — 중간에 실패해도 무엇을 어디에 두려 했는지 남아 회수할 수 있다(11/22: 고아 미끼)
    for pid in pids:
        r["placements"][pid]["status"] = "pending"
    save_reg(r)
    for pid in pids:
        p = r["placements"][pid]
        try:
            states = run_ops([(pid, p)], "apply")
        except SystemExit as e:
            p["status"] = "failed"
            event(r, "failed", pid, type=p["type"], host=p["host"], detail=str(e)[-300:])
            save_reg(r)
            print(f"실패 {pid} {p['type']} {p['host']} — recall {pid}로 정리\n{e}")
            continue
        bad = [x for x in states.get(pid, []) if x[2] == "failed"]
        p["status"] = "failed" if bad else "active"
        event(r, "placed" if not bad else "failed", pid, type=p["type"], host=p["host"], ident=p["ident"]["value"], states=states.get(pid))
        save_reg(r)
        print(f"{'배치' if not bad else '실패'} {pid} {p['type']} {p['host']} → {p['ident']['value']}")


def cmd_verify(a):
    r = load_reg()
    live = [(pid, p) for pid, p in r["placements"].items() if p["status"] == "active"]
    states = run_ops(live, "check")
    drift = [pid for pid, st in states.items() if any(s == "drift" for _, _, s in st)]
    reopen = [pid for pid, st in states.items() if any(s == "gone" for _, _, s in st) and pid not in drift]
    if reopen:  # 잊힌 세션은 재부팅으로 사라지는 게 자연스럽다 → 경보 없이 "다시 열린 세션"으로
        run_ops([(pid, r["placements"][pid]) for pid in reopen], "apply")
        for pid in reopen:
            event(r, "reopened", pid)
        print(f"세션 다시 엶 {len(reopen)}개")
    for pid in drift:
        p = r["placements"][pid]
        bad = [f"{h}#{i}" for h, i, s in states[pid] if s == "drift"]
        alert(event(r, "drift", pid, type=p["type"], host=p["host"], detail=f"사라지거나 바뀜: {bad}"))
    if drift:
        run_ops([(pid, r["placements"][pid]) for pid in drift], "apply")
        for pid in drift:
            event(r, "restored", pid)
    known = [op["line"] for p in r["placements"].values() if p["status"] == "active" for op in p["ops"] if op["kind"] == "decoy_key"]
    for d in inventory().get("decoys", []):
        aud = _run({d: [{"kind": "decoy_audit", "user": "backup", "known": known}]}, {d: [("audit", 0)]}, "check")
        if any(x[2] == "drift" for x in aud.get("audit", [])):
            alert(event(r, "orphan", "-", host=d, detail="authorized_keys에 레지스트리에 없는 키(옵션 없는 일반 키) — 자동 삭제 안 함"))
    print(f"검사 {len(live)}개, 드리프트 {len(drift)}개" + (" → 복구함" if drift else ""))
    save_reg(r)


def cmd_rotate(a):
    r = load_reg()
    targets = [pid for pid, p in r["placements"].items() if p["status"] == "active" and (a.all or pid in a.ids)]
    for old in targets:
        p = r["placements"][old]
        if p["ident"]["kind"] == "via":
            continue
        run_ops([(old, p)], "absent")
        p["status"] = "retired"   # 옛 ID는 계속 감시(쓰이면 유출 시점까지 알 수 있음)
        p["retired"] = now()
        new = build(r, {"type": p["type"], "host": p["host"], "anchor": p["anchor"], "anchor_key": p["anchor_key"]}, rotated_from=old)
        run_ops([(new, r["placements"][new])], "apply")
        event(r, "rotated", new, old=old, ident=r["placements"][new]["ident"]["value"], old_ident=p["ident"]["value"])
        print(f"교체 {old}({p['ident']['value']}) → {new}({r['placements'][new]['ident']['value']})")
    save_reg(r)


def cmd_recall(a):
    r = load_reg()
    targets = [pid for pid, p in r["placements"].items() if p["status"] in ("active", "failed", "pending")
               and (a.all or pid in a.ids or (a.host and p["host"] == a.host))]
    run_ops([(pid, r["placements"][pid]) for pid in targets], "absent")
    for pid in targets:
        r["placements"][pid]["status"] = "recalled"
        event(r, "recalled", pid)
        print(f"회수 {pid} {r['placements'][pid]['type']} {r['placements'][pid]['host']}")
    save_reg(r)


def cmd_list(a):
    r = load_reg()
    for pid, p in sorted(r["placements"].items(), key=lambda x: x[1]["created"]):
        print(f"{pid} {p['status']:8} {p['type']:12} {p['host']:10} {p['anchor_key'].split(':', 2)[2]:28} {p['ident']['value']}")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("collect").set_defaults(f=lambda a: collect())
    for n, f in (("plan", cmd_plan), ("apply", cmd_apply), ("verify", cmd_verify), ("list", cmd_list)):
        sp.add_parser(n).set_defaults(f=f)
    for n, f in (("rotate", cmd_rotate), ("recall", cmd_recall)):
        p = sp.add_parser(n)
        p.add_argument("ids", nargs="*")
        p.add_argument("--all", action="store_true")
        if n == "recall":
            p.add_argument("--host")
        p.set_defaults(f=f)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
