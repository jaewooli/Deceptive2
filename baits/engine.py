#!/usr/bin/env python3
"""미끼 배포 엔진 — Illusive식 맥락 기반 원격 배포(01-vendor-feature-map 문제 1)를 Ansible 위에.
  python3 baits/engine.py collect          서버 맥락 수집(읽기 전용) → out/baits/context/<호스트>.json
  python3 baits/engine.py plan             맥락 + 레지스트리 → 새로 둘 자리 / 맥락이 사라진 자리(회수 후보)
  python3 baits/engine.py apply            plan대로 배치하고 레지스트리에 기록
  python3 baits/engine.py verify           주기 재적용: 사라지거나 바뀐 미끼 = 경보 + 복구(드리프트)
  python3 baits/engine.py rotate [ID|--all] 고유 ID 교체. 옛 ID는 retired로 남겨 계속 감시
  python3 baits/engine.py recall [ID|--host H|--all]  깨끗하게 회수
  python3 baits/engine.py list
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
    active = {p["anchor_key"]: pid for pid, p in r["placements"].items() if p["status"] == "active"}
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
    act = [p for p in r["placements"].values() if p["type"] == "projection" and p["status"] in ("active", "pending")]
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
    run = (f"set -euo pipefail\ncd \"$(dirname \"$0\")\"\n"
           f"APT_SNAPSHOT={a.get('platform', {}).get('apt_snapshot') or ''} bash guest/guest.sh create {n} {a['addr']} {a['gw']} {p['mac']} {a['mem']} {farm.get('guest_cpus', 2)} {','.join(a['packages'])} mgmt.pub {'pg' if a['pg'] else ''}\n"
           f"bash guest/guest.sh offline {n}\n(cd role && GUEST_NAME={n} bash ./role.sh {' '.join(rargs)})\n"
           f"bash guest/guest.sh seal {n}\nbash guest/guest.sh online {n}\n")
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
    _, d2 = one(farm["host"], [{"kind": "run", "script": (SRV / "hosts/farm/trap/build.sh").read_text(),
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
    targets = [pid for pid, p in r["placements"].items() if p["status"] in ("active", "failed", "pending")
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
