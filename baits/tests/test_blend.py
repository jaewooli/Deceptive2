"""블렌딩 규칙 단위 테스트(baits/blend.py) — 구간 분리(11/23) 뒤 로컬 랩 모양의 합성 맥락."""
import ipaddress
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import blend  # noqa: E402

CONF = yaml.safe_load((Path(__file__).resolve().parents[1] / "projection.yml").read_text())
PLAT = {"kernel": "6.8.0-88-generic", "os": "Ubuntu 24.04.3 LTS", "packages": {"openssh-server": "1:9.6p1-3ubuntu13.20", "nginx": "1.24.0-2ubuntu7.5"}}


def ctx(addr, procs, plat=PLAT):
    return {"processes": procs, "platform": plat,
            "net": {"ifaces": [{"iface": "enp0s2", "addr": "10.0.2.15/24"}, {"iface": "enp0s3", "addr": addr}]}}


CTXS = {"web-01": ctx("10.0.21.11/24", ["nginx", "gunicorn", "sshd"]),
        "app-01": ctx("10.0.20.10/24", ["postgres", "sshd"])}
LAN = ipaddress.ip_network("10.0.20.0/23")


class Blend(unittest.TestCase):
    def test_tier_picks_segment(self):
        p = {x["template"]: x for x in blend.plan(CTXS, CONF, LAN, taken_addrs=["10.0.20.15", "10.0.20.40"])}
        self.assertEqual(p["stg"]["segment"], "10.0.21.0/24")   # 스테이징 = 웹 옆
        self.assertEqual(p["dev"]["segment"], "10.0.20.0/24")   # 개발 DB = DB 서버 옆
        self.assertEqual(p["stg"]["gw"], "10.0.21.1")

    def test_name_follows_neighbors(self):
        p = {x["template"]: x for x in blend.plan(CTXS, CONF, LAN, taken_names=["stg-01"])}
        self.assertEqual(p["stg"]["name"], "stg-02")
        self.assertEqual(p["dev"]["name"], "dev-01")

    def test_addr_after_neighbors_skips_taken(self):
        p = {x["template"]: x for x in blend.plan(CTXS, CONF, LAN, taken_addrs=["10.0.20.11"])}
        self.assertEqual(p["dev"]["addr"], "10.0.20.12/24")      # .10 다음, .11은 사용 중
        self.assertEqual(p["stg"]["addr"], "10.0.21.12/24")

    def test_reserved_low_addresses(self):
        c = {"web-01": ctx("10.0.21.2/24", ["nginx"])}
        p = blend.plan(c, CONF, LAN)
        self.assertTrue(all(int(ipaddress.ip_interface(x["addr"]).ip.packed[-1]) > 3 for x in p))

    def test_two_templates_never_share_address(self):
        one = {"app-01": ctx("10.0.20.10/24", ["postgres", "nginx"])}   # 구간 하나 → 둘 다 같은 구간
        p = blend.plan(one, CONF, LAN)
        self.assertEqual(len({x["addr"] for x in p}), 2)

    def test_platform_majority(self):
        other = dict(PLAT, kernel="6.8.0-87-generic")
        c = dict(CTXS, **{"web-02": ctx("10.0.21.12/24", ["nginx"], other), "web-03": ctx("10.0.21.13/24", ["nginx"])})
        p = {x["template"]: x for x in blend.plan(c, CONF, LAN)}
        self.assertEqual(p["stg"]["platform"]["kernel"], "6.8.0-88-generic")

    def test_placed_skipped(self):
        self.assertEqual([x["template"] for x in blend.plan(CTXS, CONF, LAN, placed=["stg"])], ["dev"])


if __name__ == "__main__":
    unittest.main()
