#!/usr/bin/env python3
"""환경 프로필(infra/env/<환경>.yml) → 미끼 엔진 입력(out/baits/inventory.yml·destinations.yml). 환경 차이는 프로필에만 둔다(docs/local-aws-parity.md).
  python3 infra/env/render.py local
레지스트리(out/baits/registry.json, 미끼 실제 값)는 건드리지 않는다. 디코이 호스트 키는 기존 값을 유지(없으면 서버에서 읽음).
"""
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__import__("os").environ.get("RENDER_OUT", ROOT / "out" / "baits"))


def main():
    env = sys.argv[1] if len(sys.argv) > 1 else "local"
    p = yaml.safe_load((ROOT / "infra/env" / f"{env}.yml").read_text())
    acc = p["access"]
    groups = {}
    for h, v in p["hosts"].items():
        if v.get("connection") == "local":
            hv = {"ansible_connection": "local", "ansible_python_interpreter": "/usr/bin/python3"}
        elif acc.get("transport") == "ssm":
            hv = {"ansible_connection": "aws_ssm", "ansible_host": v.get("instance_id")}
        else:
            hv = {"ansible_host": "127.0.0.1", "ansible_port": v["port"]}
        groups.setdefault(v["group"], {"hosts": {}})["hosts"][h] = hv
    inv = {"all": {"vars": {"ansible_user": acc["user"]}, "children": groups}}
    if acc.get("key"):
        inv["all"]["vars"]["ansible_ssh_private_key_file"] = str(Path(acc["key"]).expanduser())

    old = yaml.safe_load((OUT / "destinations.yml").read_text()) if (OUT / "destinations.yml").exists() else {}
    import hashlib
    prof = ROOT / "infra/env" / f"{env}.yml"
    # 렌더 뒤 프로필을 고치고 다시 렌더하지 않으면 엔진이 옛 값으로 돈다(11/23 실제로 일어남) → 해시를 남겨 엔진·검사가 비교
    dest = {"env": env, "profile": str(prof.relative_to(ROOT)), "profile_sha256": hashlib.sha256(prof.read_bytes()).hexdigest(),
            "lan_cidr": p["lan_cidr"]}
    for h, v in p["hosts"].items():
        if v["group"] == "decoys":
            key = (old.get(h) or {}).get("host_key")
            if not key and v.get("port"):
                key = subprocess.run([str(ROOT / "infra/local-vm/lab.sh"), "ssh", h, "cat /etc/ssh/ssh_host_ed25519_key.pub"],
                                     capture_output=True, text=True).stdout.split()[:2]
                key = " ".join(key)
            dest[h] = {"ip": v["ip"], "host_key": key}
    farm_host = next(h for h, v in p["hosts"].items() if v["group"] == "farms")
    f = p["farm"]
    dest["farm"] = {"host": farm_host, "ip": f["tunnel_endpoint"], "persist": f["persist"], "guest_cpus": f["guest"]["cpus"],
                    "guest": f["guest"]}
    sensor = next(h for h, v in p["hosts"].items() if v["group"] == "sensors")
    dest["sensor"] = {"host": sensor, "nics": {seg: s["sensor_nics"] for seg, s in p["segments"].items()}}
    dest["access"] = {k: acc.get(k) for k in ("run", "run_local", "run_decoy")}
    dest["access"]["key"] = str(Path(acc["key"]).expanduser()) if acc.get("key") else ""
    dest["access"]["local_hosts"] = [h for h, v in p["hosts"].items() if v.get("connection") == "local"]
    dest["segments"] = {seg: {"name": s["name"], "gw": s["gw"]} for seg, s in p["segments"].items()}

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "inventory.yml").write_text(yaml.safe_dump(inv, allow_unicode=True, sort_keys=False))
    (OUT / "destinations.yml").write_text(yaml.safe_dump(dest, allow_unicode=True, sort_keys=False))
    print(f"{env}: inventory {sum(len(g['hosts']) for g in groups.values())}대, 구간 {len(p['segments'])}, 팜 {farm_host}({f['tunnel_endpoint']})")


if __name__ == "__main__":
    main()
