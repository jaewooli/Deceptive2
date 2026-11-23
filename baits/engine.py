#!/usr/bin/env python3
"""미끼 배포 엔진 — Illusive식 맥락 기반 원격 배포(01-vendor-feature-map 문제 1)를 Ansible 위에.
  python3 baits/engine.py collect          서버 맥락 수집(읽기 전용) → out/baits/context/<호스트>.json
  python3 baits/engine.py plan             맥락 + 레지스트리 → 새로 둘 자리 / 맥락이 사라진 자리(회수 후보)
  python3 baits/engine.py apply            plan대로 배치하고 레지스트리에 기록
  python3 baits/engine.py verify           주기 재적용: 사라지거나 바뀐 미끼 = 경보 + 복구(드리프트)
  python3 baits/engine.py rotate [ID|--all] 고유 ID 교체. 옛 ID는 retired로 남겨 계속 감시
  python3 baits/engine.py recall [ID|--host H|--all]  깨끗하게 회수
  python3 baits/engine.py list
기능 켜고 끄기: python3 baits/engine.py feature projection|trap on|off / feature - status
투영 디코이(projection): plan이 blend.py로 구간·이름·주소를 정하고, apply가 센서 투영 + 팜 KVM VM을 만든다(destinations.yml의 sensor.nics 필요)
레지스트리: out/baits/registry.json(로컬, 커밋 안 함 — 미끼 실제 값이 들어 있음). AWS에선 비공개 S3(11/28)
목적지: out/baits/destinations.yml  {db-backup-01: {ip: ...}}
경보: 환경변수 BAIT_WEBHOOK_URL(없으면 표준 출력)
"""
import argparse
import base64
import io
import ipaddress
import json
import os
import secrets
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import bait_types as T  # noqa: E402
import blend  # noqa: E402

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
            "agent_session": ("user",), "sync_service": ("name",), "decoy_port": ("port",), "cache_hint": ("path",)}[tname]
    return f"{tname}:{host}:" + ":".join(str(a[k]) for k in pick)


# ------------------------------------------------------------------ 계획
def constraints():
    p = HERE / "constraints.yml"
    return {d["anchor"]: d["reason"] for d in (yaml.safe_load(p.read_text()) or {}).get("deny", [])} if p.exists() else {}


def plan(r, ctxs):
    deny = constraints()
    active = {p["anchor_key"]: pid for pid, p in r["placements"].items() if p["status"] in ("active", "paused")}   # paused = 기능 꺼 둠(자리 유지)
    off = off_types(r)
    used = {p["ident"]["value"] for p in r["placements"].values()}
    new, seen = [], set()
    live_ports = [{"host": p["host"], "service": p["anchor"]["service"], "port": p["anchor"]["port"]}
                  for p in r["placements"].values() if p["type"] == "decoy_port" and p["status"] == "active"]
    for host, ctx in ctxs.items():
        ctx["_decoy_ports"] = live_ports
        for tname, t in T.TYPES.items():
            for a in (t.match(ctx, host, dests()) if tname == "decoy_port" else t.match(ctx, host)):
                key = anchor_key(tname, host, a)
                if key in seen:  # 같은 파일을 여러 서비스가 쓰면 규칙이 같은 자리를 여러 번 찾는다(11/22 중복 배치)
                    continue
                seen.add(key)
                if key in active or tname in off:
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
    if "projection" not in off:
        new += plan_projection(r, ctxs)
    return new, gone


# ------------------------------------------------------------------ 투영 디코이(Acalvio 투영 + 규칙 블렌딩, HANDOFF 8절)
def projection_conf():
    return yaml.safe_load((HERE / "projection.yml").read_text())


def plan_projection(r, ctxs):
    """주변 회사 서버 맥락 → 역할 템플릿마다 구간·이름·주소(blend.py). 이미 있는 역할은 건너뜀"""
    d = dests()
    if "sensor" not in d:
        return []
    company = inventory().get("company", [])
    cx = {h: c for h, c in ctxs.items() if h in company}
    act = [p for p in r["placements"].values() if p["type"] == "projection" and p["status"] in ("active", "pending", "paused")]
    taken = [v["ip"] for v in d.values() if isinstance(v, dict) and "ip" in v] + [p["anchor"]["addr"].split("/")[0] for p in act]
    names = [p["anchor"]["name"] for p in act] + [k for k in d if isinstance(d[k], dict)]
    lan = ipaddress.ip_network(d.get("lan_cidr", "10.0.0.0/16"))
    out = []
    for a in blend.plan(cx, projection_conf(), lan, taken, names, [p["anchor"]["template"] for p in act]):
        if not (SRV / "hosts/farm/roles" / a["template"] / "role.sh").exists():
            print(f"건너뜀  projection   {a['name']} — 역할 스크립트 없음(servers/hosts/farm/roles/{a['template']}/role.sh)")
            continue
        if not d["sensor"]["nics"].get(a["segment"]):
            print(f"건너뜀  projection   {a['name']} — 센서에 {a['segment']} NIC 없음")
            continue
        out.append({"type": "projection", "host": d["farm"]["host"], "anchor": a, "anchor_key": f"projection:{d['farm']['host']}:{a['template']}"})
    return out


def _tgz(files):
    """{묶음 안 경로: 로컬 경로 | bytes} → base64 tgz"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for arc, src in files.items():
            if isinstance(src, bytes):
                ti = tarfile.TarInfo(arc); ti.size = len(src); ti.mode = 0o644
                t.addfile(ti, io.BytesIO(src))
            else:
                t.add(src, arc, filter=lambda x: None if "__pycache__" in x.name or x.name.endswith("README.md") else x)
    return base64.b64encode(buf.getvalue()).decode()


def role_extras(a):
    """역할마다 배포 묶음에 더 넣을 것과 role.sh 인자"""
    import tempfile
    d = dests()
    if a["template"] == "stg":   # 2025-05-12(12단계)까지의 앱 이력, 공통 PG 설정, 옮겨 온 데이터 생성기, db-backup-01 호스트 키
        tmp = Path(tempfile.mkdtemp())
        subprocess.run([sys.executable, str(SRV / "webapp-history/build_history.py"), "--out", str(tmp / "app"), "--until", "12"],
                       check=True, capture_output=True)
        dbb = d[T.DECOY]
        return ({"role/app": str(tmp / "app"), "role/base/postgresql": str(SRV / "base/postgresql"),
                 "role/carryover/make_carryover.py": str(SRV / "hosts/db-backup-01/carryover/make_carryover.py"),
                 "role/dbb_hostkey.pub": (dbb["host_key"] + "\n").encode()},
                [".", dbb["ip"], "dbb_hostkey.pub"])
    if a["template"] == "dev":   # 앱 이력(12단계), 공통 PG 설정, 데이터 생성기, known_hosts용 호스트 키(stg 디코이·web-01·db-backup-01)
        tmp = Path(tempfile.mkdtemp())
        subprocess.run([sys.executable, str(SRV / "webapp-history/build_history.py"), "--out", str(tmp / "app"), "--until", "12"],
                       check=True, capture_output=True)
        dbb = d[T.DECOY]
        stg = next((p["anchor"] for p in load_reg()["placements"].values()
                    if p["type"] == "projection" and p["status"] == "active" and p["anchor"]["template"] == "stg"), None)
        if not stg:
            raise SystemExit("dev 역할은 stg 디코이를 가리킨다(git remote·known_hosts) — stg를 먼저 배치")
        _, sk = one(d["farm"]["host"], [{"kind": "bundle", "tgz": _tgz({"guest": str(SRV / "hosts/farm/guest")}), "entry": "guest/guest.sh",
                                         "argv": ["hostkey", stg["name"]], "collect": ["hostkey"]}])
        _, wk = one("web-01", [{"kind": "run", "argv": [], "collect": ["hostkey"],
                                "script": "echo hostkey=$(awk '{print $2}' /etc/ssh/ssh_host_ed25519_key.pub)\n"}])
        web_ip = next(ipaddress.ip_interface(i["addr"]).ip for i in contexts()["web-01"]["net"]["ifaces"]
                      if ipaddress.ip_interface(i["addr"]).ip in ipaddress.ip_network(d.get("lan_cidr", "10.0.0.0/16")))
        return ({"role/app": str(tmp / "app"), "role/base/postgresql": str(SRV / "base/postgresql"),
                 "role/carryover/make_carryover.py": str(SRV / "hosts/db-backup-01/carryover/make_carryover.py"),
                 "role/stg.pub": f"ssh-ed25519 {sk['hostkey']}\n".encode(), "role/web.pub": f"ssh-ed25519 {wk['hostkey']}\n".encode(),
                 "role/dbb.pub": (dbb["host_key"] + "\n").encode()},
                [".", stg["name"], stg["addr"].split("/")[0], "stg.pub", str(web_ip), "web.pub", dbb["ip"], "dbb.pub"])
    return {}, []


def whois(value):
    """active·paused·retired 모두 — 교체된 옛 미끼가 쓰이면 유출 시점을 좁힐 수 있다"""
    hit = False
    for pid, p in load_reg()["placements"].items():
        if p["ident"].get("value") == value:
            hit = True
            print(f"{pid} {p['type']} {p['host']} 상태={p['status']} 만든 때={p['created']}"
                  + (f" 교체됨={p.get('retired')}" if p.get("retired") else "") + f" 자리={p['anchor_key']}")
    if not hit:
        print("레지스트리에 없음 — 미끼가 아닌 값(정상 계정·관리 키이거나 공격자 자신의 것)")


def notify_config():
    """세 서버 moa-notify: 웹훅 = 환경 프로필, SSH 감시(sshd)는 디코이만 켬(정상 업무에서 아무도 안 들어옴), 회사 서버엔 같은 모양으로 꺼 둠"""
    n = dests()["notify"]
    sshd = {"path": "/var/log/auth.log", "settle_seconds": 3}
    for h in inventory().get("company", []) + inventory().get("decoys", []):
        st, _ = one(h, [{"kind": "moa_set", "values": {"webhook_url": n["webhook_url"], "format": n.get("format", "json")}},
                        {"kind": "moa_watch", "watch": "sshd", "enabled": h in inventory().get("decoys", []), "cfg": sshd}])
        print(h, st)


def decoy_agent_files(a):
    """디코이 안 moa-notify: 같은 구간 회사 서버의 설정을 그대로(웹훅·형식·감시 항목 모양), 주소만 디코이 것, 트랩 중계(ports)는 끔"""
    d = dests()
    lan = ipaddress.ip_network(a["segment"])
    ctx = contexts()
    nb = next((h for h in inventory().get("company", []) for i in ctx.get(h, {}).get("net", {}).get("ifaces", [])
               if ipaddress.ip_interface(i["addr"]).ip in lan), None) or inventory()["company"][0]
    _, cd = one(nb, [{"kind": "run", "argv": [], "collect": ["cfg"],
                      "script": "echo cfg=$(base64 -w0 < /etc/moa-notify/config.json)\n"}])
    cfg = json.loads(base64.b64decode(cd["cfg"]))
    ports = cfg.get("watch", {}).get("ports")
    if isinstance(ports, dict):
        ports.update({"enabled": False, "address": a["addr"].split("/")[0], "ports": []})
    m = SRV / "detection/moa-notify"
    return {"guest/moa/moa_notify.py": str(m / "moa_notify.py"), "guest/moa/moa-notify.service": str(m / "moa-notify.service"),
            "guest/moa/config.json": json.dumps(cfg, ensure_ascii=False, indent=2).encode()}, nb


def install_decoy_agent(r, pid):
    """이미 만든 투영 디코이에 moa-notify 넣기: 끄고 → 디스크에 설치 → 켜기(1분 안팎)"""
    p = r["placements"][pid]
    a, n = p["anchor"], p["anchor"]["name"]
    files, nb = decoy_agent_files(a)
    run = (f"set -euo pipefail\ncd \"$(dirname \"$0\")\"\nbash guest/guest.sh offline {n}\n"
           f"bash guest/moa.sh {n} guest/moa/moa_notify.py guest/moa/moa-notify.service guest/moa/config.json\n"
           f"bash guest/guest.sh online {n}\n")
    one(dests()["farm"]["host"], [{"kind": "bundle", "entry": "run.sh", "argv": [],
                                   "tgz": _tgz({"guest": str(SRV / "hosts/farm/guest"), "run.sh": run.encode(), **files})}])
    print(f"moa-notify → {n}(설정 모양 = {nb})")


def place_projection(r, pid):
    """센서에 투영 주소(구간 NIC 하나) → 그 NIC MAC으로 팜 VM 생성(첫 부팅: 패치·패키지·공통 베이스) → 역할 → 시작"""
    p = r["placements"][pid]
    a, d = p["anchor"], dests()
    sensor, farm = d["sensor"], d["farm"]
    busy = {q.get("nic") for q in r["placements"].values() if q["type"] == "projection" and q["status"] == "active"}
    nic = next((n for n in sensor["nics"][a["segment"]] if n not in busy), None)
    if not nic:
        raise SystemExit(f"센서 {a['segment']}에 빈 NIC 없음(디코이 하나 = NIC 하나 — 같은 MAC에 여러 서버가 묶이면 ARP 캐시에서 드러남)")
    _, sd = one(sensor["host"], [{"kind": "run", "script": (SRV / "hosts/sensor/install.sh").read_text(),
                                  "argv": ["add", nic, a["addr"], a["gw"]], "collect": ["projection_mac"]}])
    p["nic"], p["mac"] = nic, sd["projection_mac"]
    save_reg(r)
    extras, rargs = role_extras(a)
    key = Path(yaml.safe_load((OUT / "inventory.yml").read_text())["all"]["vars"]["ansible_ssh_private_key_file"] + ".pub")
    n = a["name"]
    g = farm["guest"]   # 환경 프로필(infra/env/<환경>.yml)의 값 — 코드엔 환경 분기 없음
    redirect = ";".join(f"{r['proto']}:{r['to']}:{r['port']}>{r['via']}" for r in g.get("build_redirect") or [])
    genv = (f"GUEST_HW={g['hw']} DISK_GB={g['disk_gb']} GUEST_DNS={g['dns']} APT_PROXY='{g.get('apt_proxy') or ''}' "
            f"BASE_IMAGE='{os.path.expanduser(g.get('base_image') or '')}' CWAGENT_MODE={g['cwagent_mode']} PERSIST={str(farm.get('persist', True)).lower()} BUILD_REDIRECT='{redirect}'")
    run = (f"set -euo pipefail\ncd \"$(dirname \"$0\")\"\n"
           f"{genv} APT_SNAPSHOT={a.get('platform', {}).get('apt_snapshot') or ''} APT_SNAPSHOT_SECURITY={a.get('platform', {}).get('apt_snapshot_security') or ''} APT_MANUAL_UPGRADE={a.get('platform', {}).get('apt_manual_upgrade') or ''} bash guest/guest.sh create {n} {a['addr']} {a['gw']} {p['mac']} {a['mem']} {g['cpus']} {','.join(a['packages'])} mgmt.pub {'pg' if a['pg'] else ''}\n"
           f"bash guest/guest.sh offline {n}\n(cd role && GUEST_NAME={n} bash ./role.sh {' '.join(rargs)})\n"
           f"bash guest/moa.sh {n} guest/moa/moa_notify.py guest/moa/moa-notify.service guest/moa/config.json\n"
           f"bash guest/guest.sh seal {n}\nbash guest/guest.sh online {n}\n")
    if g.get("mirror_files"):   # 진짜 서버에만 손으로 둔 로컬 전용 파일을 그대로(권한·소유자·시각) — 값은 저장소에 없음
        rel = " ".join(f.lstrip("/") for f in g["mirror_files"])
        _, md = one(g["mirror_from"], [{"kind": "run", "argv": [], "collect": ["mirror"],
                                        "script": f"echo mirror=$(tar -C / -czf - {rel} | base64 -w0)\n"}])
        extras["guest/mirror.tgz"] = base64.b64decode(md["mirror"])
    agent, _ = decoy_agent_files(a)
    extras.update(agent)
    files = {"guest": str(SRV / "hosts/farm/guest"), "guest/base": str(SRV / "base"),
             "role": str(SRV / "hosts/farm/roles" / a["template"]), "mgmt.pub": key.read_bytes(), "run.sh": run.encode(), **extras}
    one(farm["host"], [{"kind": "bundle", "tgz": _tgz(files), "entry": "run.sh", "argv": []}])
    p["ops"] = [{"kind": "unit", "name": f"guest@{n}.service", "on_host": farm["host"]}]


def recall_projection(r, pid):
    p = r["placements"][pid]
    a, d = p["anchor"], dests()
    n, x = a["name"], a["addr"].split("/")[0]
    one(d["farm"]["host"], [{"kind": "run", "argv": [], "script": f"""systemctl disable --now guest@{n} 2>/dev/null
findmnt -rno SOURCE /var/lib/machines/{n} >/dev/null && umount -R /var/lib/machines/{n}; [ -f /run/guest-{n}.nbd ] && qemu-nbd -d $(cat /run/guest-{n}.nbd) >/dev/null; rm -f /run/guest-{n}.nbd
ip rule del pref 49 iif ve-{n} lookup main 2>/dev/null; nft delete table ip guest_build 2>/dev/null   # 빌드 중 중단됐을 때의 NAT
rm -f /var/lib/guests/{n}.qcow2 /var/lib/guests/{n}-* /etc/guest/{n}.env /etc/guest/{n}.pub /etc/systemd/network/10-ve-{n}.network /var/log/guests/{n}.log
while ip rule del iif ve-{n} lookup 120 2>/dev/null; do :; done
ip route del {x}/32 2>/dev/null; ip route del blackhole {x}/32 metric 1000 2>/dev/null; networkctl reload 2>/dev/null; true
"""}])
    one(d["sensor"]["host"], [{"kind": "run", "script": (SRV / "hosts/sensor/install.sh").read_text(), "argv": ["remove", x]}])


def dests():
    p = OUT / "destinations.yml"
    if not p.exists():
        raise SystemExit(f"{p} 없음 — python3 infra/env/render.py <환경> 먼저(환경 값은 infra/env/에만)")
    d = yaml.safe_load(p.read_text())
    check_profile(d)
    return d


def check_profile(d):
    """렌더한 뒤 프로필이 바뀌었으면 멈춘다(옛 값으로 배치하지 않게 — 11/23 복사 목록이 빠진 빌드)"""
    import hashlib
    prof = HERE.parent / d.get("profile", "")
    if not d.get("profile_sha256") or not prof.is_file():
        raise SystemExit("destinations.yml에 프로필 해시 없음 — python3 infra/env/render.py <환경>")
    if hashlib.sha256(prof.read_bytes()).hexdigest() != d["profile_sha256"]:
        raise SystemExit(f"{d['profile']}이 렌더 뒤 바뀜 — python3 infra/env/render.py {d.get('env', '<환경>')} 다시")


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
            h = op["decoy"] if op["kind"] == "decoy_key" else op.get("on_host", p["host"])
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
                j = json.loads(res["stdout"])
                LAST_DATA[h] = j.get("data", {})
                for x in j["results"]:
                    pid, i = index[h][x["i"]]
                    states.setdefault(pid, []).append((h, i, x["state"]))
    return states


LAST_DATA = {}
SRV = HERE.parent / "servers"


def one(host, ops, mode="apply"):
    """한 호스트에 작업 묶음 하나 → (상태들, 돌려받은 데이터)"""
    LAST_DATA.pop(host, None)
    st = _run({host: ops}, {host: [("x", i) for i in range(len(ops))]}, mode)
    states = [x[2] for x in st.get("x", [])]
    data = LAST_DATA.get(host, {})
    if "failed" in states:
        raise SystemExit(f"{host}: 실패 {data.get('error', '')}")
    return states, data


def edh_ports(r, host, extra=None, drop=None):
    ports = {p["anchor"]["port"] for p in r["placements"].values()
             if p["type"] == "decoy_port" and p["host"] == host and p["status"] == "active"}
    if extra:
        ports.add(extra)
    if drop:
        ports.discard(drop)
    return sorted(ports)


def place_decoy_port(r, pid):
    """EDH 키 → farm 트랩(EDH 공개키) → EDH 터널(farm 공개키) → 공통 데몬의 ports 설정"""
    p = r["placements"][pid]
    a, host = p["anchor"], p["host"]
    farm = dests()["farm"]
    slots = r.setdefault("farm_slots", {})
    n = slots.setdefault(host, max(slots.values(), default=0) + 1)
    _, d = one(host, [{"kind": "wg_key", "name": "wg0", "as": "edh_pub"}])
    trap = f"trap-{host}"
    _, d2 = one(farm["host"], [{"kind": "run", "script": f"export PERSIST={str(farm.get('persist', True)).lower()}\n" + (SRV / "hosts/farm/trap/build.sh").read_text(),
                                "argv": [trap, host, str(n), a["service"], str(a["port"]), a["addr"], a["gw"], d["edh_pub"]],
                                "collect": ["farm_tunnel_public_key"]}])
    one(host, [{"kind": "run", "script": (SRV / "detection/edh-tunnel.sh").read_text(),
                "argv": [f"{farm['ip']}:{51820 + n}", d2["farm_tunnel_public_key"]]},
               {"kind": "ports_config", "address": a["addr"].split("/")[0], "iface": a["iface"], "ports": edh_ports(r, host, extra=a["port"])}])
    # 이후 검사(verify)·회수에 쓰는 작업: EDH 설정 + farm 트랩 서비스
    p["ops"] = [{"kind": "ports_config", "address": a["addr"].split("/")[0], "iface": a["iface"], "ports": edh_ports(r, host, extra=a["port"])},
                {"kind": "unit", "name": f"systemd-nspawn@{trap}.service", "on_host": farm["host"]}]
    p["farm_slot"] = n


def recall_decoy_port(r, pid):
    p = r["placements"][pid]
    a, host = p["anchor"], p["host"]
    rest = edh_ports(r, host, drop=a["port"])
    one(host, [{"kind": "ports_config", "address": a["addr"].split("/")[0], "iface": a["iface"], "ports": rest}])
    if not rest:  # 이 EDH에 넘길 포트가 없으면 터널도 내린다
        one(host, [{"kind": "run", "script": "systemctl disable --now wg-quick@wg0 2>/dev/null; rm -f /etc/wireguard/wg0.conf /etc/wireguard/wg0.key\n", "argv": []}])
        farm = dests()["farm"]
        n = r.get("farm_slots", {}).get(host)
        one(farm["host"], [{"kind": "run", "argv": [], "script": f"""systemctl disable --now systemd-nspawn@trap-{host} wg-quick@edh{n} 2>/dev/null
rm -rf /etc/systemd/nspawn/trap-{host}.nspawn /etc/systemd/system/systemd-nspawn@trap-{host}.service.d /usr/local/lib/relay/trap-trap-{host}-up \
  /etc/systemd/network/10-ve-trap-{host}.network /etc/wireguard/edh{n}.conf /etc/wireguard/edh{n}.key
ip rule del pref {60 + n} 2>/dev/null; ip rule del pref {161 + n} 2>/dev/null; systemctl daemon-reload
"""}])


# ------------------------------------------------------------------ 기능 켜고 끄기(벤더 기술 단위, 11/23 사용자 요청)
# 끔 = 네트워크에서 그 기능이 없던 상태(경로·규칙·터널·ARP 응답 제거, 디코이는 멈춤 — 디스크·키는 남김). 켬 = 같은 자리·같은 ID로 되살림
FEATURES = {   # 스위치 = 시중 벤더 기술 단위(11/23 사용자: 끄면 그 기술의 방식이 환경에서 전부 사라져야, 자체 설계는 끄지 않음)
    "breadcrumbs": ("Illusive 맥락 기반 미끼(T1~T6, US10382483)",
                    ["env_db_url", "ssh_config", "history", "agent_session", "aws_profile", "sync_service"]),
    "trap": ("Illusive 트랩 서버 중계(빈 포트 → 팜 트랩 + 활성 트랩만 가리키는 cache_hint, US10404747)", ["decoy_port", "cache_hint"]),
    "conntable": ("Attivo 연결 테이블 미끼(핸드셰이크만 한 연결 + 디코이 페이로드 관문, US10375110)", []),
    "projection": ("Acalvio 투영(센서 → 팜 디코이 VM)", ["projection"]),
}
# 항상 켜 둠(자체 설계 — 특정 벤더 기술이 아님): db-backup-01 옛 백업 서버 디코이, moa-notify, 랩 장치·검사 도구


def feature_state(r, name):
    return r.get("features", {}).get(name, "on")


def off_types(r):
    return {t for n, (_, ts) in FEATURES.items() if feature_state(r, n) == "off" for t in ts}


def _pause(r, pid):
    r["placements"][pid]["status"] = "paused"; event(r, "paused", pid); save_reg(r)


def _resume(r, pid):
    r["placements"][pid]["status"] = "active"; event(r, "resumed", pid); save_reg(r)


def sync_refresh(r):
    """report-sync(T5)는 두 기술을 싣는다: 미끼 계정(Illusive 맥락 미끼) + 핸드셰이크만 한 연결(Attivo). 두 스위치 상태대로 다시 만든다"""
    crumbs, conn = feature_state(r, "breadcrumbs") == "on", feature_state(r, "conntable") == "on"
    for pid, p in r["placements"].items():
        if p["type"] != "sync_service" or p["status"] not in ("active", "paused"):
            continue
        if not crumbs and not conn:
            if p["status"] == "active":
                run_ops([(pid, p)], "absent"); _pause(r, pid)
            continue
        p["ops"] = T.TYPES["sync_service"].ops(p["anchor"], p["ident"], dests()[T.DECOY], crumbs=crumbs, conn=conn)
        # 디코이 이름 풀이(/etc/hosts 줄)는 T1 미끼가 넣는다 — Illusive를 꺼도 Attivo 연결은 이름을 풀어야 하므로 같은 줄을 함께 갖는다
        # (같은 서버 T1 배치의 작업을 그대로 — 조건을 새로 짐작하지 않음, 11/23 미끼만 끄면 연결이 안 되던 원인)
        hosts_ops = [op for q in r["placements"].values() if q["type"] == "env_db_url" and q["host"] == p["host"]
                     and q["status"] in ("active", "paused") for op in q["ops"] if op.get("path") == "/etc/hosts"]
        p["ops"] += hosts_ops[:1]
        if hosts_ops:   # hosts 줄이 바뀌면(미끼를 끄고 켜는 사이) 바로 다시 연결하게 — 안 그러면 이름 풀이 실패 뒤 60초 쉼
            for op in p["ops"]:
                if op["kind"] == "unit":
                    op["files"] = op.get("files", []) + ["/etc/hosts"]
        run_ops([(pid, p)], "apply")
        if p["status"] != "active":
            _resume(r, pid)
        save_reg(r)


def gate_apply(r):
    """Attivo 페이로드 관문: 디코이 moa-notify의 gate 감시를 켜고 끈다(끄면 데몬이 TPROXY 규칙을 지움 — moa_notify teardown)"""
    on = feature_state(r, "conntable") == "on"
    for h in inventory().get("decoys", []):
        one(h, [{"kind": "moa_watch", "watch": "gate", "enabled": on}])


def projection_off(r):
    d = dests()
    for pid, p in [(k, v) for k, v in r["placements"].items() if v["type"] == "projection" and v["status"] == "active"]:
        a = p["anchor"]
        one(d["farm"]["host"], [{"kind": "run", "argv": [], "script": f"systemctl stop guest@{a['name']} 2>/dev/null; true\n"}])
        one(d["sensor"]["host"], [{"kind": "run", "script": (SRV / "hosts/sensor/install.sh").read_text(), "argv": ["remove", a["addr"].split("/")[0]]}])
        _pause(r, pid)
    for h in (d["sensor"]["host"], d["farm"]["host"]):   # relay는 투영 전용 터널
        one(h, [{"kind": "run", "argv": [], "script": "systemctl disable --now wg-quick@relay >/dev/null 2>&1; true\n"}])


def projection_on(r):
    d = dests()
    persist = str(d["farm"].get("persist", True)).lower() == "true"
    for h, en in ((d["farm"]["host"], persist), (d["sensor"]["host"], True)):
        one(h, [{"kind": "run", "argv": [], "script": f"{'systemctl enable wg-quick@relay >/dev/null 2>&1; ' if en else ''}systemctl start wg-quick@relay\n"}])
    for pid, p in [(k, v) for k, v in r["placements"].items() if v["type"] == "projection" and v["status"] == "paused"]:
        a = p["anchor"]
        _, sd = one(d["sensor"]["host"], [{"kind": "run", "script": (SRV / "hosts/sensor/install.sh").read_text(),
                                           "argv": ["add", p["nic"], a["addr"], a["gw"]], "collect": ["projection_mac"]}])
        if sd.get("projection_mac") != p["mac"]:
            raise SystemExit(f"{a['name']}: 센서 NIC MAC이 바뀜({p['mac']} → {sd.get('projection_mac')}) — 디코이 NIC MAC과 어긋나 ARP에서 드러남")
        one(d["farm"]["host"], [{"kind": "run", "argv": [], "script": f"systemctl start guest@{a['name']}\n"}])
        _resume(r, pid)


def trap_off(r):
    d = dests()
    ports = [(k, v) for k, v in r["placements"].items() if v["type"] == "decoy_port" and v["status"] == "active"]
    hints = [(k, v) for k, v in r["placements"].items() if v["type"] == "cache_hint" and v["status"] == "active"]
    if hints:
        run_ops(hints, "absent")
        for pid, _ in hints:
            _pause(r, pid)
    for h in sorted({p["host"] for _, p in ports}):
        a = next(p["anchor"] for _, p in ports if p["host"] == h)
        n = r.get("farm_slots", {}).get(h)
        one(h, [{"kind": "ports_config", "address": a["addr"].split("/")[0], "iface": a["iface"], "ports": []},
                {"kind": "run", "argv": [], "script": "systemctl disable --now wg-quick@wg0 >/dev/null 2>&1; true\n"}])
        one(d["farm"]["host"], [{"kind": "run", "argv": [], "script": f"systemctl disable --now systemd-nspawn@trap-{h} wg-quick@edh{n} >/dev/null 2>&1; true\n"}])
    for pid, _ in ports:
        _pause(r, pid)


def trap_on(r):
    d = dests()
    persist = str(d["farm"].get("persist", True)).lower() == "true"
    ports = [(k, v) for k, v in r["placements"].items() if v["type"] == "decoy_port" and v["status"] == "paused"]
    for pid, _ in ports:
        r["placements"][pid]["status"] = "active"
    for h in sorted({p["host"] for _, p in ports}):
        a = next(p["anchor"] for _, p in ports if p["host"] == h)
        n = r.get("farm_slots", {}).get(h)
        one(d["farm"]["host"], [{"kind": "run", "argv": [], "script":
            f"{'systemctl enable wg-quick@edh%s systemd-nspawn@trap-%s >/dev/null 2>&1; ' % (n, h) if persist else ''}"
            f"systemctl start wg-quick@edh{n} systemd-nspawn@trap-{h}\n"}])
        one(h, [{"kind": "run", "argv": [], "script": "systemctl enable --now wg-quick@wg0 >/dev/null 2>&1\n"},
                {"kind": "ports_config", "address": a["addr"].split("/")[0], "iface": a["iface"], "ports": edh_ports(r, h)}])
    for pid, _ in ports:
        _resume(r, pid)
    hints = [(k, v) for k, v in r["placements"].items() if v["type"] == "cache_hint" and v["status"] == "paused"]
    if hints:
        run_ops(hints, "apply")
        for pid, _ in hints:
            _resume(r, pid)


def breadcrumbs_off(r):
    live = [(k, v) for k, v in r["placements"].items() if v["type"] in FEATURES["breadcrumbs"][1] and v["type"] != "sync_service"
            and v["status"] == "active"]
    if live:
        run_ops(live, "absent")
        for pid, _ in live:
            _pause(r, pid)


def breadcrumbs_on(r):
    paused = [(k, v) for k, v in r["placements"].items() if v["type"] in FEATURES["breadcrumbs"][1] and v["type"] != "sync_service"
              and v["status"] == "paused"]
    if paused:
        run_ops(paused, "apply")
        for pid, _ in paused:
            _resume(r, pid)


def feature_set(r, name, state):
    r.setdefault("features", {})[name] = state
    save_reg(r)
    if name == "projection":
        (projection_on if state == "on" else projection_off)(r)
    elif name == "trap":
        (trap_on if state == "on" else trap_off)(r)
    elif name == "breadcrumbs":
        (breadcrumbs_on if state == "on" else breadcrumbs_off)(r)
        sync_refresh(r)
    elif name == "conntable":
        sync_refresh(r)
        gate_apply(r)


def cmd_feature(a):
    r = load_reg()
    if a.state == "status":
        for n, (desc, types) in FEATURES.items():
            ps = [p for p in r["placements"].values() if p["type"] in types and p["status"] in ("active", "paused")]
            print(f"{n:11} {feature_state(r, n):3}  {desc} — 배치 {len(ps)}개"
                  f" ({', '.join(sorted({p['status'] for p in ps})) or '-'})")
        return
    feature_set(r, a.name, a.state)
    print(f"{a.name} {a.state}")


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
            if p["type"] == "decoy_port":
                place_decoy_port(r, pid)
                states = {pid: [(p["host"], 0, "changed")]}
            elif p["type"] == "projection":
                place_projection(r, pid)
                states = {pid: [(p["host"], 0, "changed")]}
            else:
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
    for pid, st in list(states.items()):
        if any(x == "released" for _, _, x in st):
            p = r["placements"][pid]
            port = p["anchor"].get("port")
            if port in LAST_DATA.get(p["host"], {}).get("released", []) or p["type"] == "decoy_port":
                p["status"] = "released"
                alert(event(r, "released", pid, type=p["type"], host=p["host"],
                            detail=f"{port} 포트를 실제 프로그램이 쓰기 시작해 디코이에서 뺌(특허: 양보). 비면 다음 plan에서 다시 제안"))
                states.pop(pid)
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


def cmd_refresh(a):
    """미끼 정의(템플릿)를 고친 뒤: 같은 ID로 내용만 다시 만들어 적용(안 하면 verify가 서버의 새 내용을 드리프트로 보고 되돌린다)"""
    r = load_reg()
    targets = [pid for pid, p in r["placements"].items() if p["status"] == "active" and p["type"] not in ("decoy_port", "projection")
               and (a.all or pid in a.ids)]
    for pid in targets:
        p = r["placements"][pid]
        p["ops"] = T.TYPES[p["type"]].ops(p["anchor"], p["ident"], dests()[T.DECOY])
        run_ops([(pid, p)], "apply")
        event(r, "refreshed", pid)
        print(f"갱신 {pid} {p['type']} {p['host']}")
    save_reg(r)


def cmd_recall(a):
    r = load_reg()
    targets = [pid for pid, p in r["placements"].items() if p["status"] in ("active", "failed", "pending", "paused")
               and (a.all or pid in a.ids or (a.host and p["host"] == a.host))]
    for pid in [t for t in targets if r["placements"][t]["type"] == "decoy_port"]:
        recall_decoy_port(r, pid)
        r["placements"][pid]["status"] = "recalled"
    for pid in [t for t in targets if r["placements"][t]["type"] == "projection"]:
        recall_projection(r, pid)
        r["placements"][pid]["status"] = "recalled"
    run_ops([(pid, r["placements"][pid]) for pid in targets if r["placements"][pid]["type"] not in ("decoy_port", "projection")], "absent")
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
    wh = sp.add_parser("whois", help="경보에 나온 값(키 지문·DB 계정·AWS 키 ID)이 어느 미끼인지 — 서버 밖에서 레지스트리로(서버엔 미끼 목록을 두지 않음)")
    wh.add_argument("value")
    wh.set_defaults(f=lambda a: whois(a.value))
    nc = sp.add_parser("notify-config", help="세 서버(회사·디코이) moa-notify 웹훅을 환경 프로필 값으로 통일")
    nc.set_defaults(f=lambda a: notify_config())
    ap_ = sp.add_parser("decoy-agent", help="이미 만든 투영 디코이에 moa-notify(회사 표준 구성) 넣기")
    ap_.add_argument("template")
    ap_.set_defaults(f=lambda a: install_decoy_agent(load_reg(), next(pid for pid, p in load_reg()["placements"].items()
                     if p["type"] == "projection" and p["status"] == "active" and p["anchor"]["template"] == a.template)))
    fp = sp.add_parser("feature", help="벤더 기능 켜고 끄기: feature projection|trap on|off, feature - status")
    fp.add_argument("name", choices=[*FEATURES, "-"])
    fp.add_argument("state", choices=["on", "off", "status"])
    fp.set_defaults(f=cmd_feature)
    for n, f in (("rotate", cmd_rotate), ("recall", cmd_recall), ("refresh", cmd_refresh)):
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
