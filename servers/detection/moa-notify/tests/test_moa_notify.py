"""moa-notify 단위 테스트 (서버에 올리지 않음)
실행: python3 -m unittest discover -s servers/detection/moa-notify/tests
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import moa_notify as mn  # noqa: E402

FIXTURES = HERE / "fixtures"


def feed_all(watcher, lines):
    out = []
    for line in lines:
        out += watcher.feed(line)
    return out


class PgConnectionsTest(unittest.TestCase):
    def setUp(self):
        self.w = mn.PgConnections({"settle_seconds": 0}, "db-backup-01")

    def test_password_failed_nonexistent_role(self):
        ev = feed_all(self.w, [
            "2026-11-20 12:00:00.100 KST [4242] LOG:  connection received: host=10.0.1.15 port=53110",
            '2026-11-20 12:00:00.130 KST [4242] report_ro@moayeyak FATAL:  password authentication failed for user "report_ro"',
            '2026-11-20 12:00:00.130 KST [4242] report_ro@moayeyak DETAIL:  Role "report_ro" does not exist.',
        ])
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["client"], "10.0.1.15:53110")
        self.assertEqual(ev[0]["user"], "report_ro")
        self.assertEqual(ev[0]["database"], "moayeyak")
        self.assertEqual(ev[0]["result"], "비밀번호 인증 실패")

    def test_authorized_then_disconnect_is_one_event(self):
        ev = feed_all(self.w, [
            "2026-11-20 12:00:01.000 KST [5000] LOG:  connection received: host=[local]",
            "2026-11-20 12:00:01.010 KST [5000] postgres@postgres LOG:  connection authorized: user=postgres database=postgres application_name=psql",
            "2026-11-20 12:00:05.000 KST [5000] postgres@postgres LOG:  disconnection: session time: 0:00:03.990 user=postgres database=postgres host=[local]",
        ])
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["result"], "접속 성공")
        self.assertEqual(ev[0]["client"], "[local]")

    def test_port_scan_without_startup(self):
        ev = feed_all(self.w, [
            "2026-11-20 12:00:02.000 KST [5100] LOG:  connection received: host=10.0.2.20 port=40000",
            "2026-11-20 12:00:02.001 KST [5100] [unknown]@[unknown] LOG:  incomplete startup packet",
        ])
        self.assertEqual(len(ev), 1)
        self.assertIsNone(ev[0]["user"])
        self.assertEqual(ev[0]["result"], "시작 패킷 이상")

    def test_received_only_is_flushed_by_tick(self):
        self.assertEqual(feed_all(self.w, [
            "2026-11-20 12:00:03.000 KST [5200] LOG:  connection received: host=10.0.2.21 port=40001",
        ]), [])
        ev = self.w.tick()
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["result"], "결과 기록 없음")

    def test_no_hba_entry(self):
        ev = feed_all(self.w, [
            "2026-11-20 12:00:04.000 KST [5300] LOG:  connection received: host=192.0.2.9 port=40002",
            '2026-11-20 12:00:04.002 KST [5300] sync_svc@backup FATAL:  no pg_hba.conf entry for host "192.0.2.9", user "sync_svc", database "backup", no encryption',
        ])
        self.assertEqual(ev[0]["user"], "sync_svc")
        self.assertEqual(ev[0]["database"], "backup")
        self.assertEqual(ev[0]["result"], "허용되지 않은 접속")

    def test_unrelated_lines_ignored(self):
        self.assertEqual(feed_all(self.w, [
            "2026-11-20 12:00:00.000 KST [900] LOG:  checkpoint starting: time",
            "2026-11-20 12:00:00.000 KST [900] LOG:  database system is ready to accept connections",
            "\tConnection matched file \"/etc/postgresql/16/main/pg_hba.conf\" line 132",
        ]), [])
        self.assertEqual(self.w.tick(), [])

    def test_pid_reuse_after_finish(self):
        lines = [
            "2026-11-20 12:00:00.100 KST [6000] LOG:  connection received: host=10.0.1.15 port=1",
            '2026-11-20 12:00:00.130 KST [6000] a@b FATAL:  password authentication failed for user "a"',
        ]
        self.assertEqual(len(feed_all(self.w, lines)), 1)
        self.assertEqual(len(feed_all(self.w, lines)), 1)

    def test_captured_fixture(self):
        """로컬 VM의 실제 PostgreSQL 16 로그(fixtures/pg16-*.log)로 확인."""
        for path in sorted(FIXTURES.glob("pg16-*.log")):
            expected = json.loads(path.with_suffix(".expected.json").read_text())
            w = mn.PgConnections({"settle_seconds": 0}, "t")
            ev = feed_all(w, path.read_text().splitlines()) + w.tick()
            got = [{k: e[k] for k in ("user", "result")} for e in ev]
            self.assertEqual(got, expected, path.name)


class FollowerTest(unittest.TestCase):
    def test_append_truncate_rotate_and_resume(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.log")
            Path(p).write_text("old\n")
            state = {}
            f = mn.Follower(p, state, "k")
            self.assertEqual(f.lines(), [])  # 처음엔 끝부터
            with open(p, "a") as fh:
                fh.write("a\npartial")
            self.assertEqual(f.lines(), ["a"])
            with open(p, "a") as fh:
                fh.write("-done\n")
            self.assertEqual(f.lines(), ["partial-done"])
            # copytruncate
            with open(p, "r+") as fh:
                fh.truncate(0)
            with open(p, "a") as fh:
                fh.write("b\n")
            self.assertEqual(f.lines(), ["b"])
            # 이름 바꾸기 rotate
            with open(p, "a") as fh:
                fh.write("c\n")
            os.rename(p, p + ".1")
            Path(p).write_text("d\n")
            self.assertEqual(f.lines(), ["c", "d"])
            # 다시 시작하면 저장한 위치부터
            with open(p, "a") as fh:
                fh.write("e\n")
            f2 = mn.Follower(p, state, "k")
            self.assertEqual(f2.lines(), ["e"])


class NotifierTest(unittest.TestCase):
    def test_post_and_rate_limit(self):
        got = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(204)
                self.end_headers()

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            n = mn.Notifier({"webhook_url": f"http://127.0.0.1:{srv.server_port}/", "format": "discord", "max_per_minute": 2})
            ev = {"host": "h", "source": "postgresql", "client": "c", "user": "u", "database": "d",
                  "result": "r", "log_ts": "t", "notified_at": "n", "lines": ["l"]}
            for _ in range(3):
                n.send(dict(ev))
            time.sleep(0.2)
            self.assertEqual(len(got), 2)
            self.assertIn("user=u", got[0]["content"])
            self.assertEqual(n.held, 1)
        finally:
            srv.shutdown()



class NotifierBadUrlTest(unittest.TestCase):
    """11/23: web-01 설정의 웹훅이 채워지지 않은 템플릿 값('{{ webhook_url }}')이라 경보 순간 ValueError로 데몬이 죽어 재시작 반복"""

    def test_bad_url_does_not_raise(self):
        n = mn.Notifier({"webhook_url": "{{ webhook_url }}", "format": "json"})
        with self.assertLogs(mn.log, level="ERROR"):
            n.send({"host": "web-01", "source": "test", "result": "x"})



class SshSessionsTest(unittest.TestCase):
    """디코이 SSH 목적지 탐지(11/23) — OpenSSH 9.6, LogLevel VERBOSE 로그 형식"""

    def feed(self, lines):
        w = mn.SshSessions({}, "lt-decoy")
        out = []
        for l in lines:
            out += w.feed(l)
        return out

    def test_bait_key_login_alerts_immediately_with_fingerprint(self):
        ev = self.feed([
            "2026-11-23T21:00:00.1+09:00 lt-decoy sshd[100]: Connection from 10.0.21.11 port 40000 on 10.0.20.15 port 22 rdomain \"\"",
            "2026-11-23T21:00:00.2+09:00 lt-decoy sshd[100]: Accepted key ED25519 SHA256:AAA found at /backup/.ssh/authorized_keys:2",
            "2026-11-23T21:00:00.3+09:00 lt-decoy sshd[100]: Accepted publickey for backup from 10.0.21.11 port 40000 ssh2: ED25519 SHA256:AAA"])
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["client"], "10.0.21.11:40000")
        self.assertEqual(ev[0]["user"], "backup")
        self.assertIn("SHA256:AAA", ev[0]["result"])
        self.assertTrue(ev[0]["result"].startswith("로그인 성공"))

    def test_retired_key_failure_carries_fingerprint(self):
        ev = self.feed([
            "2026-11-23T21:00:00.1+09:00 lt-decoy sshd[200]: Connection from 10.0.21.11 port 40001 on 10.0.20.15 port 22 rdomain \"\"",
            "2026-11-23T21:00:00.2+09:00 lt-decoy sshd[200]: Failed publickey for backup from 10.0.21.11 port 40001 ssh2: ED25519 SHA256:OLD",
            "2026-11-23T21:00:00.3+09:00 lt-decoy sshd[200]: Connection closed by authenticating user backup 10.0.21.11 port 40001 [preauth]"])
        self.assertEqual(len(ev), 1)
        self.assertIn("SHA256:OLD", ev[0]["result"])
        self.assertTrue(ev[0]["result"].startswith("인증 실패"))

    def test_lines_after_login_are_not_new_events(self):
        ev = self.feed([
            "2026-11-23T21:00:00.1+09:00 lt-decoy sshd[400]: Connection from 10.0.21.11 port 40003 on 10.0.20.15 port 22 rdomain \"\"",
            "2026-11-23T21:00:00.3+09:00 lt-decoy sshd[400]: Accepted publickey for backup from 10.0.21.11 port 40003 ssh2: ED25519 SHA256:AAA",
            "2026-11-23T21:00:01.0+09:00 lt-decoy sshd[400]: Received disconnect from 10.0.21.11 port 40003:11: disconnected by user",
            "2026-11-23T21:00:01.0+09:00 lt-decoy sshd[400]: Disconnected from user backup 10.0.21.11 port 40003"])
        self.assertEqual(len(ev), 1)

    def test_user_child_pid_lines_belong_to_login(self):
        """실제 로그(11/23 디코이): 로그인 뒤 종료 줄은 사용자 자식 pid에서 나온다"""
        ev = self.feed([
            'x lt-decoy sshd[9848]: Connection from 10.0.21.11 port 48824 on 10.0.20.15 port 22 rdomain ""',
            "x lt-decoy sshd[9848]: Postponed publickey for backup from 10.0.21.11 port 48824 ssh2 [preauth]",
            "x lt-decoy sshd[9848]: Accepted publickey for backup from 10.0.21.11 port 48824 ssh2: ED25519 SHA256:AAA",
            "x lt-decoy sshd[9848]: User child is on pid 9911",
            "x lt-decoy sshd[9911]: Received disconnect from 10.0.21.11 port 48824:11: disconnected by user",
            "x lt-decoy sshd[9911]: Disconnected from user backup 10.0.21.11 port 48824"])
        self.assertEqual(len(ev), 1)

    def test_banner_grab_is_one_event(self):
        ev = self.feed([
            "2026-11-23T21:00:00.1+09:00 lt-decoy sshd[300]: Connection from 10.0.21.11 port 40002 on 10.0.20.15 port 22 rdomain \"\"",
            "2026-11-23T21:00:00.2+09:00 lt-decoy sshd[300]: Connection closed by 10.0.21.11 port 40002 [preauth]"])
        self.assertEqual([e["result"] for e in ev], ["인증 전 끊김"])

    def test_unrelated_lines_ignored(self):
        self.assertEqual(self.feed(["2026-11-23T21:00:00+09:00 lt-decoy sshd[1]: Server listening on 0.0.0.0 port 22."]), [])


class ProjectionInTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        open(os.path.join(self.d, "stg-01.env"), "w").write("ADDR=10.0.21.12/24\nMEM=1024\n")
        self.w = mn.ProjectionIn({"guest_env_dir": self.d}, "farm")

    def test_tcp_new_connection_names_decoy(self):
        ev = self.w.feed("2026-11-23T21:30:00.000+09:00 farm kernel: PROJ-IN IN=relay OUT=ve-stg-01 SRC=10.0.21.11 DST=10.0.21.12 "
                         "LEN=60 TOS=0x00 PREC=0x00 TTL=64 ID=1 DF PROTO=TCP SPT=40000 DPT=22 WINDOW=64240 RES=0x00 SYN URGP=0")
        self.assertEqual(ev[0]["client"], "10.0.21.11:40000")
        self.assertIn("stg-01(10.0.21.12:22/TCP)", ev[0]["result"])

    def test_icmp_without_ports(self):
        ev = self.w.feed("2026-11-23T21:30:00.000+09:00 farm kernel: PROJ-IN IN=relay OUT=ve-stg-01 SRC=10.0.20.10 DST=10.0.21.12 "
                         "LEN=84 TOS=0x00 PREC=0x00 TTL=64 ID=1 DF PROTO=ICMP TYPE=8 CODE=0 ID=5 SEQ=1")
        self.assertIn("stg-01(10.0.21.12/ICMP)", ev[0]["result"])

    def test_other_prefix_ignored(self):
        self.assertEqual(self.w.feed("2026-11-23T21:30:00+09:00 farm kernel: IN-FWD SRC=1.1.1.1 DST=2.2.2.2 PROTO=TCP SPT=1 DPT=2"), [])


if __name__ == "__main__":
    unittest.main()
