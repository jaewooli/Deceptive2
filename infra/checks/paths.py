#!/usr/bin/env python3
"""검사 실행기 — 경로 단언·공격자 시점·디코이 안쪽 명세를 같은 방식으로 돌린다(트래픽 거의 없이 몇 초).

왜(11/22~23 장애): 경로표가 비면 패킷은 조용히 다른 길로 간다(투영 응답이 터널을 우회 → SSH 키 교환 멈춤),
local 규칙이 지워지면 서버 전체가 먹통이 된다. 둘 다 배포·재부팅 뒤 "상태"의 문제라 정적 검사로는 못 잡는다.

  python3 infra/checks/paths.py infra/checks/paths.spec [--host H]
환경(로컬·AWS)은 명세에 박지 않는다(docs/local-aws-parity.md 원칙 2·4):
  - 주소·이름은 자리표시자 — 실행 때 out/baits/(render.py 결과·레지스트리·맥락)에서 채운다
      {ip:<호스트>}            회사 LAN 주소(회사 서버는 맥락, 디코이는 destinations, 투영 디코이는 이름으로)
      {proj:<템플릿>:<필드>}   투영 디코이: name·ip·addr·mac·nic·gw (레지스트리의 active 배치)
      {trap:<서버>:tun|port}   그 서버의 트랩 중계(레지스트리): 팜 쪽 터널 이름·넘기는 포트
      {if:<서버>}              그 서버의 회사 LAN NIC 이름(맥락 — 로컬 enp0s3, AWS ens5)
      {feat:<기술>} {nofeat:<기술>}  빈 문자열 — 그 벤더 기술 스위치가 켜져(꺼져) 있을 때만 채워짐 → 줄 하나를 켬/끔 상태에만 검사
      {farm} {sensor}          그 역할의 호스트 이름
  - 기대값은 같은 환경의 진짜 서버에서 그때 잰다: same / samehost
  - 접속 방법은 destinations.yml의 access(run·run_decoy)

명세 한 줄: 호스트 | 종류 | 인자 | 기대 | 설명
  route    : 인자 = `ip route get`의 인자, 기대 = 나가는 장치(dev) 또는 blackhole/unreachable
  has      : 인자 = 셸 명령, 기대 = 출력에 있어야 하는 정규식
  hasnt    : 인자 = 셸 명령, 기대 = 출력에 없어야 하는 정규식
  same     : 인자 = {T}가 든 셸 명령, 기대 = "<정규식(그룹 1)> @ <대상 A> ~ <대상 B>" — 같은 호스트에서 T=A, T=B로 돌려 뽑은 값이 같아야
  samehost : 호스트 = "<A> ~ <B>", 인자 = 셸 명령, 기대 = 정규식(그룹 1) — 두 호스트에서 돌려 뽑은 값이 같아야(디코이 안 vs 진짜 서버)
자리표시자를 못 채우면(예: 아직 배치 안 된 투영 디코이) 그 줄은 "건너뜀"으로 센다(실패 아님, 따로 표시).
서버에는 아무 파일도 남기지 않는다(스크립트는 표준입력으로).
"""
import argparse
import ipaddress
import json
import re
import shlex
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out" / "baits"
KINDS = ("route", "has", "hasnt", "same", "samehost")


class Missing(Exception):
    pass


def variables():
    dest = yaml.safe_load((OUT / "destinations.yml").read_text())
    import hashlib
    prof = ROOT / dest.get("profile", "")
    if not prof.is_file() or hashlib.sha256(prof.read_bytes()).hexdigest() != dest.get("profile_sha256"):
        sys.exit(f"환경 프로필이 렌더 뒤 바뀜(또는 해시 없음) — python3 infra/env/render.py {dest.get('env', '<환경>')} 다시")
    lan = ipaddress.ip_network(dest.get("lan_cidr", "10.0.0.0/16"))
    v = {"farm": dest["farm"]["host"], "sensor": dest["sensor"]["host"]}
    for f in (OUT / "context").glob("*.json"):
        for i in json.loads(f.read_text()).get("net", {}).get("ifaces", []):
            if ipaddress.ip_interface(i["addr"]).ip in lan:
                v[f"ip:{f.stem}"] = str(ipaddress.ip_interface(i["addr"]).ip)
                v[f"if:{f.stem}"] = i["iface"]
    for h, d in dest.items():
        if isinstance(d, dict) and "ip" in d and h not in ("farm",):
            v.setdefault(f"ip:{h}", d["ip"])
    reg = json.loads((OUT / "registry.json").read_text()) if (OUT / "registry.json").exists() else {"placements": {}}
    feats = reg.get("features", {})
    for name in ("breadcrumbs", "trap", "conntable", "projection", "forensics"):   # 벤더 기술 스위치(engine.py FEATURES)
        v[f"feat:{name}" if feats.get(name, "on") == "on" else f"nofeat:{name}"] = ""
    for p in reg["placements"].values():
        if p["type"] == "projection" and p["status"] == "active":
            a = p["anchor"]
            t = a["template"]
            v.update({f"proj:{t}:name": a["name"], f"proj:{t}:addr": a["addr"], f"proj:{t}:ip": a["addr"].split("/")[0],
                      f"proj:{t}:gw": a["gw"], f"proj:{t}:mac": p.get("mac", ""), f"proj:{t}:nic": p.get("nic", "")})
            v[f"ip:{a['name']}"] = a["addr"].split("/")[0]
        if p["type"] == "decoy_port" and p["status"] == "active" and p.get("farm_slot"):
            v[f"trap:{p['host']}:tun"] = f"edh{p['farm_slot']}"
            v[f"trap:{p['host']}:port"] = str(p["anchor"]["port"])
    return v, dest


def fill(s, v, regex=False):
    def sub(m):
        k = m.group(1)
        if k not in v:
            raise Missing(k)
        return re.escape(v[k]) if regex else v[k]
    return re.sub(r"\{((?:ip|if|proj|trap|feat|nofeat):[^{}]+|farm|sensor)\}", sub, s)


def load(spec, v):
    checks, skipped = [], []
    for n, line in enumerate(Path(spec).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(" | ")]
        if len(parts) != 5 or parts[1] not in KINDS:
            sys.exit(f"{spec}:{n}: 형식 오류(구분자는 ' | '): {line}")
        c = dict(zip(("host", "kind", "arg", "want", "why"), parts), line=n)
        try:
            c["host"] = fill(c["host"], v)
            c["arg"] = fill(c["arg"], v)
            if c["kind"] == "same":
                rx, targets = c["want"].rsplit(" @ ", 1)
                c["rx"] = rx
                c["targets"] = [fill(t.strip(), v) for t in targets.split("~")]
            elif c["kind"] in ("has", "hasnt", "samehost"):
                c["want"] = fill(c["want"], v, regex=True)
            else:
                c["want"] = fill(c["want"], v)
        except Missing as e:
            skipped.append((c["why"], str(e)))
            continue
        checks.append(c)
    return checks, skipped


def script_for(cmds):
    out = ["exec 2>&1"]
    for i, cmd in enumerate(cmds):
        out.append(f"echo; echo @@{i}")   # 앞 명령 출력이 줄바꿈 없이 끝나도(curl -w) 구분 표시가 붙지 않게
        out.append(f"( {cmd} ) </dev/null || true")   # 명령이 나머지 스크립트(표준입력)를 먹지 않게
    out.append("echo; echo @@end")
    return "\n".join(out) + "\n"


def transport(host, dest):
    acc = dest.get("access", {})
    projs = {v for k, v in VARS.items() if k.startswith("proj:") and k.endswith(":ip")}
    tpl = acc.get("run_decoy") if host in projs else acc.get("run_local") if host in acc.get("local_hosts", []) else acc.get("run")
    if not tpl:
        raise SystemExit("destinations.yml에 access.run 없음 — python3 infra/env/render.py <환경>")
    return tpl.format(host=shlex.quote(host), root=ROOT, key=acc.get("key", ""))


def run_host(host, cmds, dest):
    try:
        r = subprocess.run(transport(host, dest), shell=True, input=script_for(cmds), capture_output=True, text=True, timeout=90)
        raw, err = r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        raw, err = "", "시간 초과(90초)"
    if "@@end" not in raw:
        print(f"  ! {host} 접속 실패: {(err or raw).strip().splitlines()[-1:] or ['(출력 없음)']}")
        return None
    blocks = re.split(r"^@@(\d+|end)$", raw, flags=re.M)
    return {int(blocks[k]): blocks[k + 1] for k in range(1, len(blocks) - 1, 2) if blocks[k].isdigit()}


def first(text):
    return (text.strip().splitlines() or ["(출력 없음)"])[0][:80]


def extract(rx, text):
    m = re.search(rx, text, re.M)
    return " ".join(g or "" for g in m.groups()) if m else None   # 그룹 여러 개면 함께 비교(예: TTL과 MSS)


def judge(c, outs):
    k = c["kind"]
    if k == "route":
        text = outs[0]
        m = re.search(r"\bdev (\S+)", text)
        got = m.group(1) if m else next((w for w in ("blackhole", "unreachable", "prohibit") if w in text), first(text))
        return got == c["want"], f"기대 {c['want']!r}, 실제 {got!r}"
    if k in ("has", "hasnt"):
        found = re.search(c["want"], outs[0], re.M) is not None
        return (found if k == "has" else not found), f"기대 {c['want']!r}, 실제 {first(outs[0])!r}"
    rx = c["rx"] if k == "same" else c["want"]
    a, b = (extract(rx, o) for o in outs)
    names = c["targets"] if k == "same" else [h.strip() for h in c["host"].split("~")]
    return (a is not None and a == b), f"{names[0]}={a!r} / {names[1]}={b!r}"


VARS = {}


def main():
    global VARS
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--host", action="append", help="이 호스트만(여러 번)")
    a = ap.parse_args()
    VARS, dest = variables()
    checks, skipped = load(a.spec, VARS)

    # 호스트별 명령 묶음: (검사 번호, 몇 번째 출력) ← 명령
    jobs = OrderedDict()
    for ci, c in enumerate(checks):
        if c["kind"] == "samehost":
            hosts = [h.strip() for h in c["host"].split("~")]
            for j, h in enumerate(hosts):
                jobs.setdefault(h, []).append((ci, j, c["arg"]))
        elif c["kind"] == "same":
            for j, t in enumerate(c["targets"]):
                jobs.setdefault(c["host"], []).append((ci, j, c["arg"].replace("{T}", t)))
        else:
            cmd = f"ip -o route get {c['arg']}" if c["kind"] == "route" else c["arg"]
            jobs.setdefault(c["host"], []).append((ci, 0, cmd))
    if a.host:
        jobs = OrderedDict((h, j) for h, j in jobs.items() if h in a.host)

    outs, dead = {}, set()
    for h, items in jobs.items():
        res = run_host(h, [cmd for _, _, cmd in items], dest)
        if res is None:
            dead.add(h)
            continue
        for k, (ci, j, _) in enumerate(items):
            outs.setdefault(ci, {})[j] = res.get(k, "")

    fails = 0
    for ci, c in enumerate(checks):
        hosts = [x.strip() for x in c["host"].split("~")]
        if a.host and not set(hosts) & set(a.host):
            continue
        if set(hosts) & dead:
            print(f"✗ {c['host']:<12} {c['kind']:<8} {c['why']}  (접속·실행 실패)")
            fails += 1
            continue
        n = 2 if c["kind"] in ("same", "samehost") else 1
        ok, detail = judge(c, [outs.get(ci, {}).get(j, "") for j in range(n)])
        fails += not ok
        print(f"{'✓' if ok else '✗'} {c['host']:<12} {c['kind']:<8} {c['why']}" + ("" if ok else f"  ({detail})"))
    for why, key in skipped:
        print(f"· 건너뜀 {why}  ({{{key}}} 없음 — 아직 배치 안 됨)")
    print(f"\n{'통과' if not fails else f'실패 {fails}개'}" + (f", 건너뜀 {len(skipped)}개" if skipped else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
