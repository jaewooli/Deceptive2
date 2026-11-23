#!/usr/bin/env python3
"""투영 디코이 블렌딩 — Acalvio가 AI로 하는 "주변과 섞이게"를 규칙으로(HANDOFF 8절 3번).
주변 서버 맥락(engine.py collect 결과)만 보고, 역할 템플릿(projection.yml)마다 정한다:
  구간   = 그 역할과 같은 계층(web·data — 도는 프로세스로 판정)의 서버가 가장 많은 서브넷
  이름   = 이웃 이름 규칙(<역할>-<NN>, 자릿수도 이웃과 같게)에서 비어 있는 번호
  주소   = 그 구간 회사 서버 번호 중 가장 큰 것 다음 빈 번호(나중에 추가된 서버처럼). 예약(.0~.3, 마지막)·사용 중 제외
  플랫폼 = 그 구간 이웃의 커널·OS·패키지 버전(같은 이미지 + 같은 패치 → 배너·서버 응답이 같아야 함). 이웃끼리 다르면 다수
결과에는 "왜 이 자리인가"를 같이 남긴다(보고서·학습 로그용).

  python3 baits/blend.py            # out/baits/context/*.json(company 그룹) + 레지스트리의 기존 투영으로 계획 출력
"""
import ipaddress
import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

HERE = Path(__file__).parent
OUT = HERE.parent / "out" / "baits"


def host_tiers(ctx, tiers):
    procs = set(ctx.get("processes", []))
    return sorted(t for t, names in tiers.items() if procs & set(names))


def segments(ctxs, lan, tiers):
    seg = {}
    for host, ctx in ctxs.items():
        for i in ctx.get("net", {}).get("ifaces", []):
            ifc = ipaddress.ip_interface(i["addr"])
            if ifc.ip in lan:
                seg.setdefault(ifc.network, []).append({"host": host, "ip": ifc.ip, "tiers": host_tiers(ctx, tiers),
                                                        "platform": ctx.get("platform", {})})
    return seg


def majority(values):
    vals = [v for v in values if v]
    return Counter(vals).most_common(1)[0][0] if vals else None


def name_for(prefix, names):
    widths = [len(m.group(2)) for n in names if (m := re.match(r"^([a-z]+)-(\d+)$", n))]
    w = majority(widths) or 2
    k = 1
    while f"{prefix}-{k:0{w}d}" in names:
        k += 1
    return f"{prefix}-{k:0{w}d}", w


def plan(ctxs, conf, lan, taken_addrs=(), taken_names=(), placed=()):
    tiers = conf["tiers"]
    seg = segments(ctxs, lan, tiers)
    if not seg:
        return []
    names = set(ctxs) | set(taken_names)
    taken = {ipaddress.ip_address(a) for a in taken_addrs}
    out = []
    for key, t in conf["templates"].items():
        if key in placed:
            continue
        why = []
        score = {net: (sum(t["tier"] in m["tiers"] for m in members), len(members)) for net, members in seg.items()}
        net = max(score, key=lambda n: score[n])
        same = [m["host"] for m in seg[net] if t["tier"] in m["tiers"]]
        why.append(f"구간 {net}: {t['tier']} 계층 서버 {', '.join(same) or '없음(서버가 가장 많은 구간)'}")
        name, w = name_for(key, names)
        names.add(name)
        why.append(f"이름 {name}: 이웃 이름 규칙 <역할>-<{w}자리 번호>({', '.join(sorted(ctxs))})")
        nums = sorted(int(m["ip"]) - int(net.network_address) for m in seg[net])
        used = taken | {m["ip"] for m in seg[net]}
        k = max(max(nums) + 1, conf.get("reserved_low", 3) + 1)
        while net.network_address + k in used:
            k += 1
        if k >= net.num_addresses - 1:
            raise SystemExit(f"{net}에 빈 주소 없음")
        a = net.network_address + k
        taken.add(a)
        why.append(f"주소 {a}: 이 구간 회사 서버 번호 {nums} 다음 빈 번호(나중에 추가된 서버처럼)")
        plats = [m["platform"] for m in seg[net]] or [c.get("platform", {}) for c in ctxs.values()]
        kernel = majority(p.get("kernel") for p in plats)
        osname = majority(p.get("os") for p in plats)
        pkgs = {}
        for p in set(t.get("packages", [])) | {"openssh-server"}:
            v = majority(pl.get("packages", {}).get(p) for pl in [c.get("platform", {}) for c in ctxs.values()])
            if v:
                pkgs[p] = v
        snap = majority(p.get("apt_snapshot") for p in plats)
        snap_sec = majority(p.get("apt_snapshot_security") for p in plats)
        serial = majority(p.get("image_serial") for p in plats)
        manual = majority(p.get("apt_manual_upgrade") for p in plats)
        why.append(f"플랫폼: 이웃 다수 커널 {kernel}, {osname}, 패키지 {pkgs}, 이미지 serial {serial}, 아카이브 스냅숏 일반 {snap}·보안 {snap_sec}(이웃의 마지막 apt 작업·unattended-upgrade), 직접 업그레이드 {manual or '없음'}")
        out.append({"template": key, "name": name, "segment": str(net), "addr": f"{a}/{net.prefixlen}",
                    "gw": str(net.network_address + 1), "services": t["services"], "packages": t["packages"],
                    "pg": bool(t.get("pg")), "mem": t["mem"], "platform": {"kernel": kernel, "os": osname, "packages": pkgs, "apt_snapshot": snap, "apt_snapshot_security": snap_sec, "image_serial": serial,
                                 "apt_manual_upgrade": manual},
                    "why": why})
    return out


def main():
    conf = yaml.safe_load((HERE / "projection.yml").read_text())
    dest = yaml.safe_load((OUT / "destinations.yml").read_text())
    inv = yaml.safe_load((OUT / "inventory.yml").read_text())["all"]["children"]
    company = list(inv["company"]["hosts"])
    ctxs = {h: json.loads((OUT / "context" / f"{h}.json").read_text()) for h in company if (OUT / "context" / f"{h}.json").exists()}
    reg = json.loads((OUT / "registry.json").read_text()) if (OUT / "registry.json").exists() else {"placements": {}}
    proj = [p for p in reg["placements"].values() if p["type"] == "projection" and p["status"] == "active"]
    taken = [dest[h]["ip"] for h in dest if isinstance(dest[h], dict) and "ip" in dest[h]] + [p["args"]["addr"].split("/")[0] for p in proj]
    lan = ipaddress.ip_network(dest.get("lan_cidr", "10.0.0.0/16"))
    for p in plan(ctxs, conf, lan, taken, [p["args"]["name"] for p in proj] + list(dest), [p["args"]["template"] for p in proj]):
        print(json.dumps({k: v for k, v in p.items() if k != "why"}, ensure_ascii=False))
        for w in p["why"]:
            print("   ·", w)


if __name__ == "__main__":
    sys.exit(main())
