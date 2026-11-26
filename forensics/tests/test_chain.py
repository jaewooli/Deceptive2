"""침투 체인 상관분석 단위 테스트(11/26) — 레지스트리·주소는 직접 채움(실제 랩 값 아님)"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import chain  # noqa: E402

REG = {"placements": {
    "b1": {"type": "ssh_config", "host": "web", "status": "active", "anchor_key": "ssh_config:web:deploy",
           "ident": {"kind": "ssh_key", "value": "SHA256:AAA"}, "ops": [{"kind": "dir", "path": "/home/deploy/.ssh"},
                                                                        {"kind": "block", "path": "/home/deploy/.ssh/config"}]},
    "b0": {"type": "ssh_config", "host": "web", "status": "retired", "anchor_key": "ssh_config:web:deploy",
           "ident": {"kind": "ssh_key", "value": "SHA256:OLD"}, "ops": [{"kind": "block", "path": "/home/deploy/.ssh/config"}]},
    "b2": {"type": "env_db_url", "host": "web", "status": "active", "anchor_key": "env_db_url:web:/srv/app/.env:URL",
           "ident": {"kind": "db_user", "value": "rpt"}, "ops": [{"kind": "line", "path": "/srv/app/.env"}, {"kind": "line", "path": "/etc/hosts"}]},
}}


def audit(host, path, ses, pid="100", auid="deploy", key="secret-files"):
    return {"host": host, "source": "감사", "client": f"cat[{pid}]", "result": f"열람: {path}", "log_ts": "2026-11-26T20:00:00+09:00",
            "audit": {"key": key, "pid": pid, "ppid": "99", "auid": auid, "ses": ses, "uid": "deploy", "exe": "/usr/bin/cat", "paths": [path]}}


def sshd(client, ts="2026-11-26T20:00:05+09:00", fp="SHA256:AAA"):
    return {"host": "decoy", "source": "sshd", "client": f"{client}:5000", "user": "backup", "result": f"공개키 {fp}", "log_ts": ts}


class ChainTest(unittest.TestCase):
    def setUp(self):
        self.ctx = chain.Ctx(REG, {"10.9.0.11": "web"}, {"web-01": "web", "web": "web"})
        self.ctx.is_collector = lambda host, *p: host == "web" and "777" in p
        self.ch = chain.Chains(self.ctx, window=600)

    def test_bait_read_then_decoy_login_is_one_chain(self):
        self.ch.add(audit("web-01", "/home/deploy/.ssh/config", "5"), 1)
        self.ch.add(sshd("10.9.0.11"), 2)
        self.ch.add({"host": "decoy", "source": "세션", "client": "10.9.0.11", "user": "backup", "log_ts": "2026-11-26T20:00:20+09:00",
                     "session": {"end": True, "commands": [{"argv": ["id"]}], "files": []}}, 3)
        self.assertEqual(len(self.ch.chains), 1)
        s = chain.Chains.summary(next(iter(self.ch.chains.values())))
        self.assertTrue(s["confirmed"])
        self.assertEqual([b["id"] for b in s["baits"]], ["b1"])   # 옛(retired) 배치는 지금 배치가 있으면 빠짐
        self.assertEqual((s["account"], s["decoys"], s["commands"]), ("deploy", ["decoy"], ["id"]))

    def test_management_origin_and_collector_ignored(self):
        self.assertIsNone(self.ch.add(sshd("10.0.2.2"), 1))                       # 회사 서버가 아닌 출발
        self.assertIsNone(self.ch.add(audit("web-01", "/home/deploy/.ssh/config", "9", pid="777"), 2))   # 수집기 자신
        self.assertEqual(self.ch.chains, {})

    def test_hosts_file_is_not_bait_and_other_activity_needs_same_session(self):
        self.ch.add(audit("web-01", "/srv/app/.env", "5"), 1)
        self.assertIsNone(self.ch.add(audit("web-01", "/etc/hosts", "6"), 2))
        self.assertIsNone(self.ch.add(audit("web-01", "/etc/cron.d/x", "6", key="persistence"), 3))   # 다른 세션
        c = self.ch.add(audit("web-01", "/etc/cron.d/x", "5", key="persistence"), 4)
        self.assertEqual([l["kind"] for l in c["links"]], ["미끼 열람", "출발지 행동"])

    def test_window_splits_chains(self):
        self.ch.add(sshd("10.9.0.11", ts="2026-11-26T20:00:00+09:00"), 1)
        self.ch.add(sshd("10.9.0.11", ts="2026-11-26T21:00:00+09:00"), 2)
        self.assertEqual(len(self.ch.chains), 2)

    def test_forensics_moves_contact_to_its_real_session(self):
        d = tempfile.mkdtemp()
        chain.FOR = Path(d)
        (Path(d) / "c1").mkdir()
        (Path(d) / "c1" / "case.json").write_text(json.dumps({"p_key": ["web", "ses", "8"], "alert_line": 3, "summary": "P=ssh 사용자 www-data"}))
        self.ch.add(audit("web-01", "/home/deploy/.ssh/config", "5"), 1)   # 다른 사람(세션 5)
        self.ch.add(audit("web-01", "/srv/app/.env", "8", auid="unset"), 2)   # 공격자(세션 8)
        self.ch.add(sshd("10.9.0.11"), 3)                                       # 세션 모름 → 최근 체인(8)
        self.ch.add({"host": "web-01", "source": "포렌식", "case": "c1", "result": "x", "log_ts": "2026-11-26T20:00:06+09:00"}, 4)
        by_ses = {c["ses"]: [l["kind"] for l in c["links"]] for c in self.ch.chains.values()}
        self.assertEqual(by_ses["8"], ["미끼 열람", "디코이 접촉", "포렌식"])
        self.assertEqual(by_ses["5"], ["미끼 열람"])


if __name__ == "__main__":
    unittest.main()
