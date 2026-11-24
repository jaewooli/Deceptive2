#!/usr/bin/env python3
"""moa-notify: 서버 로그를 따라 읽다가 지정한 이벤트가 생기면 웹훅으로 알린다.

표준 라이브러리만 사용한다(Ubuntu 24.04 python3).
설정: /etc/moa-notify/config.json (root 0600), 예시는 config.example.json
"""
import argparse
import json
import logging
import os
import re
import socket
import sys
import time
import urllib.request
from collections import deque
from datetime import datetime

log = logging.getLogger("moa-notify")


# ---------------------------------------------------------------- 파일 따라 읽기
class Follower:
    """로그 파일 끝을 따라 읽는다. logrotate의 이름 바꾸기·copytruncate 모두 처리하고,
    다시 시작해도 읽던 위치에서 이어 읽는다."""

    def __init__(self, path, state, key):
        self.path = path
        self.state = state  # dict, 호출자가 저장
        self.key = key
        self.fh = None
        self.ino = None
        self.buf = b""

    def _open(self, from_start):
        try:
            fh = open(self.path, "rb")
        except FileNotFoundError:
            return False
        st = os.fstat(fh.fileno())
        saved = self.state.get(self.key)
        if from_start:
            pos = 0
        elif saved and saved.get("ino") == st.st_ino and saved.get("pos", 0) <= st.st_size:
            pos = saved["pos"]
        else:
            pos = st.st_size
        fh.seek(pos)
        if self.fh:
            self.fh.close()
        self.fh, self.ino, self.buf = fh, st.st_ino, b""
        return True

    def lines(self):
        """새로 생긴 완전한 줄들을 돌려준다."""
        if self.fh is None and not self._open(from_start=False):
            return []
        out = self._read()
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return out
        if st.st_ino != self.ino:
            out += self._read()  # 옛 파일에 남은 것까지 읽고 새 파일로
            self._open(from_start=True)
            out += self._read()
        elif st.st_size < self.fh.tell():
            self.fh.seek(0)  # copytruncate
            self.buf = b""
            out += self._read()
        self.state[self.key] = {"ino": self.ino, "pos": self.fh.tell() - len(self.buf)}
        return out

    def _read(self):
        data = self.fh.read()
        if not data:
            return []
        data = self.buf + data
        parts = data.split(b"\n")
        self.buf = parts.pop()
        return [p.decode("utf-8", "replace") for p in parts]


# ---------------------------------------------------------------- PostgreSQL 접속
# Ubuntu 기본 log_line_prefix = '%m [%p] %q%u@%d '
PG_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)? \S+) \[(?P<pid>\d+)\] "
    r"(?:(?P<user>\S*)@(?P<db>\S*) )?(?P<level>[A-Z]+):\s+(?P<msg>.*)$"
)
RE_RECEIVED = re.compile(r"^connection received: host=(?P<host>\S+)(?: port=(?P<port>\d+))?")
RE_AUTHORIZED = re.compile(r"^connection authorized: user=(?P<user>\S+)(?: database=(?P<db>\S+))?")
RE_DISCONN = re.compile(r"^disconnection: .*?user=(?P<user>\S+) database=(?P<db>\S+) host=(?P<host>\S+)")
RE_QUOTED_USER = re.compile(r'(?:for user|user) "(?P<user>[^"]*)"')
RE_QUOTED_DB = re.compile(r'database "(?P<db>[^"]*)"')
RE_QUOTED_HOST = re.compile(r'host "(?P<host>[^"]*)"')

PG_RESULT = [
    (re.compile(r"^password authentication failed"), "비밀번호 인증 실패"),
    (re.compile(r"^no pg_hba\.conf entry"), "허용되지 않은 접속"),
    (re.compile(r"^role .* does not exist"), "없는 계정"),
    (re.compile(r"^database .* does not exist"), "없는 DB"),
    (re.compile(r"^(?:incomplete startup packet|invalid length of startup packet|unsupported frontend protocol)"), "시작 패킷 이상"),
    (re.compile(r"^could not receive data from client"), "연결 끊김"),
    (re.compile(r"^could not accept SSL connection"), "SSL 협상 후 끊김"),
]


class PgConnections:
    """PG 서버 로그에서 클라이언트 접속 하나를 하나의 알림으로 묶는다."""

    name = "postgresql"

    def __init__(self, cfg, host):
        self.host = host
        self.settle = float(cfg.get("settle_seconds", 3))
        self.ignore_local = bool(cfg.get("ignore_local", False))
        # immediate: 접속 첫 줄에서 바로 한 번 알린다(결과 알림은 그대로 나중에) — 대응 쪽이 연결이 살아 있을 때 출발지를 볼 수 있게
        self.immediate = bool(cfg.get("immediate", False))
        self.sessions = {}  # pid -> dict
        self.finished = {}  # 알림을 보낸 pid -> 시각. 같은 접속의 뒤따르는 줄(종료 등)은 다시 알리지 않음

    def _session(self, pid, ts):
        s = self.sessions.get(pid)
        if s is None:
            s = self.sessions[pid] = {
                "pid": pid, "log_ts": ts, "client": None, "user": None, "database": None,
                "result": None, "lines": [], "last": time.monotonic(),
            }
        return s

    def feed(self, line):
        """한 줄을 넣고, 완성된 알림 목록을 돌려준다."""
        m = PG_LINE.match(line)
        if not m:
            return []
        pid, msg = m["pid"], m["msg"]
        is_conn_line = msg.startswith("connection received:")
        if is_conn_line:
            self.finished.pop(pid, None)
        elif pid in self.finished:
            return []
        known = pid in self.sessions
        if not known and not is_conn_line and not _is_conn_related(msg):
            return []
        s = self._session(pid, m["ts"])
        s["lines"].append(line)
        s["last"] = time.monotonic()
        if m["user"] and m["user"] != "[unknown]":
            s["user"] = s["user"] or m["user"]
        if m["db"] and m["db"] != "[unknown]":
            s["database"] = s["database"] or m["db"]

        if (r := RE_RECEIVED.match(msg)):
            s["client"] = r["host"] + (f":{r['port']}" if r["port"] else "")
            if r["host"] == "127.0.0.1" and r["port"] and int(r["port"]) in GATE_MAP:
                s["client"] = GATE_MAP.pop(int(r["port"])) + " (관문 경유)"
            if self.immediate and not (self.ignore_local and r["host"] == "[local]"):
                return [{"host": self.host, "source": self.name, "client": s["client"], "user": None, "database": None,
                         "result": "접속 시작", "log_ts": s["log_ts"], "pid": pid, "lines": [line]}]
            return []
        if (r := RE_AUTHORIZED.match(msg)):
            s["user"], s["database"] = r["user"], r["db"] or s["database"]
            s["result"] = "접속 성공"
            return self._finish(pid)
        if (r := RE_DISCONN.match(msg)):
            s["user"] = s["user"] or r["user"]
            s["database"] = s["database"] or r["db"]
            s["client"] = s["client"] or r["host"]
            s["result"] = s["result"] or "접속 종료"
            return self._finish(pid)
        if m["level"] in ("FATAL", "LOG"):
            for pat, label in PG_RESULT:
                if pat.match(msg):
                    if (u := RE_QUOTED_USER.search(msg)):
                        s["user"] = s["user"] or u["user"]
                    if (d := RE_QUOTED_DB.search(msg)):
                        s["database"] = s["database"] or d["db"]
                    if (h := RE_QUOTED_HOST.search(msg)):
                        s["client"] = s["client"] or h["host"]
                    s["result"] = label
                    return self._finish(pid)
        return []

    def tick(self):
        """마지막 줄 뒤로 settle_seconds가 지난 접속을 마무리한다."""
        now = time.monotonic()
        for pid in [p for p, t in self.finished.items() if now - t > 3600]:
            del self.finished[pid]
        out = []
        for pid in [p for p, s in self.sessions.items() if now - s["last"] >= self.settle]:
            s = self.sessions[pid]
            s["result"] = s["result"] or "결과 기록 없음"
            out += self._finish(pid)
        return out

    def _finish(self, pid):
        s = self.sessions.pop(pid)
        self.finished[pid] = time.monotonic()
        if self.ignore_local and s["client"] == "[local]":
            return []
        return [{
            "host": self.host,
            "source": self.name,
            "client": s["client"] or "알 수 없음",
            "user": s["user"],
            "database": s["database"],
            "result": s["result"],
            "log_ts": s["log_ts"],
            "pid": s["pid"],
            "lines": s["lines"][-6:],
        }]


def _is_conn_related(msg):
    return (msg.startswith(("connection authorized:", "disconnection:"))
            or any(p.match(msg) for p, _ in PG_RESULT))


# ---------------------------------------------------------------- SSH 접속
SSH_LINE = re.compile(r"^(?P<ts>\S+) \S+ sshd\[(?P<pid>\d+)\]: (?P<msg>.*)$")
SSH_RULES = [   # (정규식, 처리) — OpenSSH 9.6. 키 지문은 LogLevel VERBOSE에서 실패 시도에도 남는다(공통 베이스)
    (re.compile(r"^Connection from (?P<ip>\S+) port (?P<port>\d+) on "), "conn"),
    (re.compile(r"^Accepted (?P<method>\S+) for (?P<user>\S+) from (?P<ip>\S+) port (?P<port>\d+) ssh2(?:: (?P<kt>\S+) (?P<fp>SHA256:\S+))?"), "ok"),
    (re.compile(r"^Failed (?P<method>\S+) for (?:invalid user )?(?P<user>\S+) from (?P<ip>\S+) port (?P<port>\d+) ssh2(?:: (?P<kt>\S+) (?P<fp>SHA256:\S+))?"), "fail"),
    (re.compile(r"^Postponed publickey for (?P<user>\S+) from (?P<ip>\S+) port (?P<port>\d+)"), "try"),
    (re.compile(r"^Invalid user (?P<user>\S*) from (?P<ip>\S+) port (?P<port>\d+)"), "invalid"),
    (re.compile(r"^Connection closed by (?:(?:authenticating|invalid) user (?P<user>\S*) )?(?P<ip>\S+) port (?P<port>\d+) \[preauth\]"), "closed"),
    (re.compile(r"^(?:Disconnected from|Received disconnect from|Connection reset by) "), "end"),
]


class SshSessions:
    """sshd 로그에서 접속 하나(sshd 자식 pid)를 알림 하나로. 시도한 키 지문을 같이 보낸다(지문 해석은 서버 밖에서)"""

    name = "sshd"

    def __init__(self, cfg, host):
        self.host = host
        self.settle = float(cfg.get("settle_seconds", 3))
        self.immediate = bool(cfg.get("immediate", False))   # PgConnections와 같은 뜻
        self.s = {}
        self.finished = {}   # 알린 pid → 시각. 같은 접속의 뒤따르는 줄(종료 등)은 다시 알리지 않음(11/23: 로그인 성공 뒤 종료 줄이 '알 수 없음' 경보로)

    def feed(self, line):
        m = SSH_LINE.match(line)
        if not m:
            return []
        pid, msg = m["pid"], m["msg"]
        # 로그인 뒤 OpenSSH는 세션을 사용자 자식 pid로 넘긴다("User child is on pid N") — 종료 줄은 그 pid에서 나온다(11/23 실측)
        if (c := re.match(r"^User child is on pid (\d+)", msg)):
            if pid in self.finished:
                self.finished[c.group(1)] = time.monotonic()
            return []
        for rx, kind in SSH_RULES:
            r = rx.match(msg)
            if not r:
                continue
            if kind == "conn":
                self.finished.pop(pid, None)   # pid 재사용 — 새 접속
            elif pid in self.finished:
                return []
            s = self.s.setdefault(pid, {"ts": m["ts"], "client": None, "user": None, "fps": [], "result": None,
                                        "lines": [], "last": time.monotonic()})
            s["lines"].append(line)
            s["last"] = time.monotonic()
            g = r.groupdict()
            if g.get("ip"):
                s["client"] = s["client"] or f"{g['ip']}:{g['port']}"
            if g.get("user"):
                s["user"] = s["user"] or g["user"]
            if g.get("fp") and g["fp"] not in s["fps"]:
                s["fps"].append(g["fp"])
            if kind == "conn" and self.immediate:
                return [{"host": self.host, "source": self.name, "client": s["client"], "user": None, "database": None,
                         "result": "접속 시작", "log_ts": m["ts"], "pid": pid, "lines": [line]}]
            if kind == "ok":
                s["result"] = f"로그인 성공({g['method']})"
                return self._finish(pid)      # 로그인 성공은 바로 알린다
            if kind == "fail":
                s["result"] = f"인증 실패({g['method']})"
            elif kind == "invalid":
                s["result"] = "없는 계정"
            elif kind in ("closed", "end"):
                s["result"] = s["result"] or "인증 전 끊김"
                return self._finish(pid)
            return []
        return []

    def tick(self):
        now = time.monotonic()
        for pid in [p for p, t in self.finished.items() if now - t > 3600]:
            del self.finished[pid]
        out = []
        for pid in [p for p, s in self.s.items() if now - s["last"] >= self.settle]:
            self.s[pid]["result"] = self.s[pid]["result"] or "접속(결과 기록 없음)"
            out += self._finish(pid)
        return out

    def _finish(self, pid):
        s = self.s.pop(pid)
        self.finished[pid] = time.monotonic()
        return [{"host": self.host, "source": self.name, "client": s["client"] or "알 수 없음", "user": s["user"],
                 "database": None, "result": s["result"] + (f" 키 {', '.join(s['fps'])}" if s["fps"] else ""),
                 "log_ts": s["ts"], "pid": pid, "lines": s["lines"][-6:]}]


# ---------------------------------------------------------------- 안 쓰는 포트로 온 연결(전달 규칙)
RE_KLOG = re.compile(r"^(?P<ts>\S+) \S+ kernel: (?:\[[\d. ]+\] )?(?P<prefix>\S+) .*?SRC=(?P<src>\S+) DST=(?P<dst>\S+) .*?PROTO=TCP SPT=(?P<spt>\d+) DPT=(?P<dpt>\d+)")


def listening_ports():
    """지금 LISTEN 중인 TCP 포트(모든 주소). /proc만 읽는다"""
    out = set()
    for f in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            for line in open(f).read().splitlines()[1:]:
                parts = line.split()
                if parts[3] == "0A":
                    out.add(int(parts[1].rsplit(":", 1)[1], 16))
        except OSError:
            pass
    return out


class ForwardedPorts:
    """이 서버에서 쓰지 않는 포트로 온 연결을 터널 건너편 서버로 넘기고, 넘길 때마다 알린다.
    이 서버 주소:포트 → (nftables DNAT) 터널 안 주소(169.254.200.1):포트 → 건너편이 다시 이 서버 주소로 DNAT.
    conntrack이 양쪽에서 되돌려 양 끝 모두 원래 주소를 본다(masquerade면 서비스가 중계를 드러냄).
    정책 규칙(ip rule)은 쓰지 않는다 — local 경로표 규칙을 옮겼더니 networkd 재시작 때 지워져 서버 전체가 먹통이 됨(11/22).
    최악의 경우에도 넘기는 것만 꺼지고 서버는 멀쩡하다. 실제 프로그램이 그 포트를 쓰기 시작하면 그 포트만 빼고(양보) 알린다."""

    name = "ports"

    def __init__(self, cfg, host):
        self.host = host
        self.addr = cfg["address"]
        self.iface = cfg["iface"]
        self.tunnel = cfg.get("tunnel", "wg0")
        self.inner = cfg.get("inner", "169.254.200.1")
        self.prefix = cfg.get("prefix", "IN-FWD")
        self.table = cfg.get("table", "local_fwd")
        self.chain = cfg.get("ttl_chain", "LOCAL_FWD")
        self.ports = sorted(int(p["port"]) for p in cfg.get("ports", []))
        self.released = set()
        self.next_check = 0
        self.next_heal = 0
        for p in sorted(listening_ports() & set(self.ports)):  # 학습: 이미 쓰는 포트는 처음부터 넘기지 않는다
            self.released.add(p)
            log.info("포트 %d 사용 중 — 넘기지 않음", p)
        self.apply()

    def active(self):
        return [p for p in self.ports if p not in self.released]

    def _ip(self, *args, check=False):
        import subprocess
        r = subprocess.run(["/usr/sbin/ip", *args], capture_output=True, text=True)
        if check and r.returncode:
            log.error("ip %s: %s", " ".join(args), r.stderr.strip())
        return r

    @staticmethod
    def teardown(cfg):
        """넘기기를 끈(또는 설정에서 뺀) 채로 시작할 때: 예전에 건 DNAT·TTL 보정·터널 경로를 지운다 — 남기면 그 포트가 계속 터널로 간다.
        서버의 다른 규칙은 건드리지 않는다(자기 테이블·체인·경로만)"""
        import subprocess
        table, chain = cfg.get("table", "local_fwd"), cfg.get("ttl_chain", "LOCAL_FWD")
        inner, tunnel = cfg.get("inner", "169.254.200.1"), cfg.get("tunnel", "wg0")
        if subprocess.run(["/usr/sbin/nft", "list", "table", "ip", table], capture_output=True).returncode != 0:
            return   # 우리가 만든 흔적이 없으면 아무것도 안 함(fail-safe)
        subprocess.run(["/usr/sbin/nft", "delete", "table", "ip", table], capture_output=True)
        ipt = lambda *a: subprocess.run(["/usr/sbin/iptables", "-w", "-t", "mangle", *a], capture_output=True)
        while ipt("-D", "PREROUTING", "-j", chain).returncode == 0:
            pass
        ipt("-F", chain); ipt("-X", chain)
        subprocess.run(["/usr/sbin/ip", "route", "del", f"{inner}/32", "dev", tunnel], capture_output=True)

    def route_ok(self):
        return f"dev {self.tunnel}" in self._ip("route", "show", f"{self.inner}/32").stdout

    def _ipt(self, *args):
        import subprocess
        return subprocess.run(["/usr/sbin/iptables", "-w", "-t", "mangle", *args], capture_output=True, text=True)

    def ttl_ok(self):
        return self._ipt("-C", "PREROUTING", "-j", self.chain).returncode == 0

    def apply_ttl(self):
        """넘긴 연결은 이 서버와 farm에서 한 번씩 포워딩돼 TTL이 2 준다 → 공격자에게 같은 서버의 22번은 TTL 64, 넘긴 포트는 62로
        보인다(11/23 실측, nmap·p0f 단서). 포워딩하는 홉마다 들어올 때 1을 되돌린다(양방향 — traceroute에 홉이 생기지도 않게).
        nft에는 TTL 산술이 없어 iptables(xt_TTL). 체인이 지워져도 TTL만 원래대로 돌아갈 뿐 서버는 멀쩡하다."""
        if self._ipt("-n", "-L", self.chain).returncode:
            self._ipt("-N", self.chain)
        self._ipt("-F", self.chain)
        self._ipt("-A", self.chain, "-i", self.tunnel, "-j", "TTL", "--ttl-inc", "1")
        if self.active():
            self._ipt("-A", self.chain, "-i", self.iface, "-d", f"{self.addr}/32", "-p", "tcp", "-m", "multiport",
                      "--dports", ",".join(map(str, self.active())), "-j", "TTL", "--ttl-inc", "1")
        if not self.ttl_ok():
            self._ipt("-A", "PREROUTING", "-j", self.chain)

    def apply(self):
        import subprocess
        for path, val in (("/proc/sys/net/ipv4/ip_forward", "1"), (f"/proc/sys/net/ipv4/conf/{self.tunnel}/rp_filter", "2")):
            try:
                with open(path, "w") as f:
                    f.write(val)
            except OSError:
                pass
        if os.path.exists(f"/sys/class/net/{self.tunnel}"):
            self._ip("route", "replace", f"{self.inner}/32", "dev", self.tunnel, check=True)
        pre = [f"    iifname \"{self.iface}\" ip daddr {self.addr} tcp dport {p} log prefix \"{self.prefix} \" level info dnat to {self.inner}:{p}"
               for p in self.active()]
        text = (f"table ip {self.table}\ndelete table ip {self.table}\ntable ip {self.table} {{\n  chain pre {{\n"
                f"    type nat hook prerouting priority dstnat; policy accept;\n" + "\n".join(pre) + "\n  }\n}\n")
        r = subprocess.run(["/usr/sbin/nft", "-f", "-"], input=text, text=True, capture_output=True)
        if r.returncode:
            log.error("nft: %s", r.stderr.strip())
        self.apply_ttl()
        log.info("넘기는 포트: %s", ", ".join(map(str, self.active())) or "-")
        # 관리 쪽이 읽는 상태(양보한 포트는 여기서 다시 잡지 않는다 — 실제 서비스가 재시작하는 틈에 가로채면 운영 트래픽을 넘김)
        try:
            tmp = "/var/lib/moa-notify/ports.json.tmp"
            with open(tmp, "w") as f:
                json.dump({"active": self.active(), "released": sorted(self.released)}, f)
            os.replace(tmp, "/var/lib/moa-notify/ports.json")
        except OSError as e:
            log.warning("ports.json: %s", e)

    def feed(self, line):
        m = RE_KLOG.match(line)
        if not m or m.group("prefix") != self.prefix:
            return []
        return [{"host": self.host, "source": "포트", "client": f"{m.group('src')}:{m.group('spt')}", "user": None,
                 "database": None, "result": f"{m.group('dst')}:{m.group('dpt')} 연결(넘김)", "log_ts": m.group("ts"),
                 "lines": [line.split(" kernel: ", 1)[-1][:300]]}]

    def tick(self):
        now = time.monotonic()
        if now < self.next_check:
            return []
        self.next_check = now + 1
        # 터널이 늦게 뜨거나 networkd가 "외래" 경로를 지워도 5초 안에 다시 건다(11/22 재부팅·networkd 재시작 시험)
        if now >= self.next_heal:
            self.next_heal = now + 5
            if self.active() and os.path.exists(f"/sys/class/net/{self.tunnel}") and not (self.route_ok() and self.ttl_ok()):
                log.info("터널 경로 다시 설정")
                self.apply()
        busy = listening_ports() & set(self.active())
        if not busy:
            return []
        self.released |= busy
        self.apply()
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        return [{"host": self.host, "source": "포트", "client": "-", "user": None, "database": None,
                 "result": f"{p} 실제 프로그램이 사용 시작 → 넘기기 중단", "log_ts": ts, "lines": []} for p in sorted(busy)]


# ---------------------------------------------------------------- 페이로드 관문(핸드셰이크만 한 연결은 넘기지 않음)
GATE_MAP = {}  # 관문이 백엔드로 연 연결의 로컬 포트 → 진짜 출발지(PG 로그의 127.0.0.1:포트를 바꿔 쓰려고)


class PayloadGate:
    """바깥에서 이 포트로 온 연결을 투명하게(TPROXY) 받아, 첫 바이트가 오기 전까지는 서비스에 넘기지 않는다.
    페이로드 없이 끝난 연결은 알리지 않고, 첫 바이트가 오면 그 순간 알리고 서비스에 이어 준다.
    (클라이언트가 먼저 말하는 프로토콜에만 — PG는 시작 패킷을 클라이언트가 먼저 보낸다)"""

    name = "gate"

    def __init__(self, cfg, host):
        import threading, queue
        self.host = host
        self.port = int(cfg["port"])
        self.listen = int(cfg.get("listen_port", 15432))
        self.backend = (cfg.get("backend_host", "127.0.0.1"), int(cfg.get("backend_port", self.port)))
        self.mark = int(cfg.get("mark", 1))
        self.rt = int(cfg.get("table_id", 100))
        self.q = queue.Queue()
        self.quiet = 0
        self.setup()
        threading.Thread(target=self.serve, daemon=True).start()

    def setup(self):
        import subprocess
        ip = lambda *a: subprocess.run(["/usr/sbin/ip", *a], capture_output=True, text=True)
        if not re.search(rf"fwmark 0x{self.mark:x} lookup {self.rt}", ip("rule", "show").stdout):
            ip("rule", "add", "fwmark", str(self.mark), "lookup", str(self.rt))
        ip("route", "replace", "local", "0.0.0.0/0", "dev", "lo", "table", str(self.rt))
        text = (f"table ip local_gate\ndelete table ip local_gate\ntable ip local_gate {{\n  chain pre {{\n"
                f"    type filter hook prerouting priority mangle; policy accept;\n"
                f"    iifname != \"lo\" tcp dport {self.port} tproxy to 127.0.0.1:{self.listen} meta mark set {self.mark} accept\n  }}\n}}\n")
        r = subprocess.run(["/usr/sbin/nft", "-f", "-"], input=text, text=True, capture_output=True)
        if r.returncode:
            log.error("nft gate: %s", r.stderr.strip())

    @staticmethod
    def teardown(cfg):
        """관문을 끈 채로 시작할 때: 예전에 건 TPROXY·fwmark 규칙을 지운다. 남기면 PG(5432)로 오는 연결이
        아무도 듣지 않는 관문 포트로 계속 돌려져 PG에 닿지 못한다"""
        import subprocess
        mark, rt = int(cfg.get("mark", 1)), int(cfg.get("table_id", 100))
        # 우리가 만든 흔적이 있을 때만 — 없는 서버에서 경로표를 비우면 남의 경로를 지울 수 있다(fail-safe)
        ours = subprocess.run(["/usr/sbin/nft", "list", "table", "ip", "local_gate"], capture_output=True).returncode == 0 or \
            re.search(rf"fwmark 0x{mark:x} lookup {rt}\b", subprocess.run(["/usr/sbin/ip", "rule", "show"], capture_output=True, text=True).stdout)
        if not ours:
            return
        subprocess.run(["/usr/sbin/nft", "delete", "table", "ip", "local_gate"], capture_output=True)
        while subprocess.run(["/usr/sbin/ip", "rule", "del", "fwmark", str(mark), "lookup", str(rt)], capture_output=True).returncode == 0:
            pass
        subprocess.run(["/usr/sbin/ip", "route", "flush", "table", str(rt)], capture_output=True)

    def serve(self):
        import threading
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.setsockopt(socket.SOL_IP, 19, 1)  # IP_TRANSPARENT
        srv.bind(("127.0.0.1", self.listen))
        srv.listen(128)
        log.info("관문: %d (바깥 연결 → 페이로드가 와야 %s:%d)", self.port, *self.backend)
        while True:
            c, peer = srv.accept()
            threading.Thread(target=self.handle, args=(c, peer), daemon=True).start()

    def handle(self, c, peer):
        import threading
        try:
            first = c.recv(65536)  # 시간 제한 없음 — 핸드셰이크만 한 연결은 상대가 닫을 때까지 여기서 대기
        except OSError:
            first = b""
        if not first:
            self.quiet += 1  # 페이로드 없이 끝남(핸드셰이크만 한 연결) — 알리지 않음
            c.close()
            return
        ts = datetime.now().astimezone().isoformat(timespec="milliseconds")
        self.q.put({"host": self.host, "source": "관문", "client": f"{peer[0]}:{peer[1]}", "user": None, "database": None,
                    "result": f"{self.port} 첫 페이로드 {len(first)}B → 서비스로 넘김", "log_ts": ts, "lines": []})
        try:
            b = socket.create_connection(self.backend, timeout=5)
        except OSError as e:
            log.warning("관문 백엔드: %s", e)
            c.close()
            return
        GATE_MAP[b.getsockname()[1]] = f"{peer[0]}:{peer[1]}"
        b.sendall(first)

        def pump(a, z):
            try:
                while True:
                    d = a.recv(65536)
                    if not d:
                        break
                    z.sendall(d)
            except OSError:
                pass
            finally:
                for x in (a, z):
                    try:
                        x.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

        threading.Thread(target=pump, args=(b, c), daemon=True).start()
        pump(c, b)

    def feed(self, line):
        return []

    def tick(self):
        # networkd 재시작 등으로 규칙·경로가 지워지면 관문이 꺼진다(PG가 직접 받음 — 핸드셰이크만 한 연결도 PG 로그에 남음) → 5초마다 확인
        now = time.monotonic()
        if now >= getattr(self, "next_heal", 0):
            self.next_heal = now + 5
            import subprocess
            rules = subprocess.run(["/usr/sbin/ip", "rule", "show"], capture_output=True, text=True).stdout
            if not re.search(rf"fwmark 0x{self.mark:x} lookup {self.rt}", rules) or "local" not in subprocess.run(
                    ["/usr/sbin/ip", "route", "show", "table", str(self.rt)], capture_output=True, text=True).stdout:
                log.info("관문 규칙 다시 설정")
                self.setup()
        out = []
        while not self.q.empty():
            out.append(self.q.get())
        return out


# ---------------------------------------------------------------- 알림 보내기
class Notifier:
    def __init__(self, cfg):
        self.url = cfg["webhook_url"]
        if not str(self.url).startswith(("http://", "https://")):
            # 주소가 틀려도 감시는 멈추지 않는다 — 경보는 로그(journal)에만 남김(11/23: 채워지지 않은 템플릿 값으로 데몬이 죽어 재시작 반복)
            log.error("웹훅 주소가 올바르지 않음(%r) — 경보는 로그에만 남김", self.url)
        self.fmt = cfg.get("format", "json")  # discord | slack | json
        self.max_per_minute = int(cfg.get("max_per_minute", 30))
        self.sent = deque()
        self.held = 0

    def send(self, event):
        now = time.monotonic()
        while self.sent and now - self.sent[0] > 60:
            self.sent.popleft()
        if len(self.sent) >= self.max_per_minute:
            self.held += 1
            log.warning("1분 한도 초과, 보류 %d건", self.held)
            return
        if self.held:
            event = dict(event, held_before=self.held)
            self.held = 0
        self.sent.append(now)
        self._post(event)

    def _post(self, event):
        body = json.dumps(self._payload(event), ensure_ascii=False).encode()
        try:
            req = urllib.request.Request(self.url, data=body, headers={
                "Content-Type": "application/json", "User-Agent": "moa-notify/1.0"})
        except ValueError as e:   # 주소 형식 오류는 재시도해도 같다 — 데몬은 계속 돈다
            log.error("웹훅 주소 오류(%s) — 경보: %s", e, json.dumps(event, ensure_ascii=False))
            return
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    r.read()
                return
            except Exception as e:  # 네트워크 오류는 재시도
                log.warning("웹훅 실패(%d/3): %s", attempt + 1, e)
                time.sleep(1 + attempt)
        log.error("웹훅 포기: %s", json.dumps(event, ensure_ascii=False))

    def _payload(self, ev):
        if self.fmt == "json":
            return ev
        text = format_text(ev)
        if self.fmt == "discord":
            return {"content": text[:1990]}
        if self.fmt == "slack":
            return {"text": text}
        raise ValueError(f"format: {self.fmt}")


def format_text(ev):
    head = f"[{ev['host']}] {ev['source']} 접속: {ev['client']} user={ev.get('user') or '-'} db={ev.get('database') or '-'} → {ev['result']}"
    extra = f"\n(직전 1분 한도로 보류 {ev['held_before']}건)" if ev.get("held_before") else ""
    lines = "\n".join(ev.get("lines", []))
    return f"{head}\n로그 시각 {ev['log_ts']} · 알림 {ev['notified_at']}{extra}\n```\n{lines}\n```"


# ---------------------------------------------------------------- 실행
# ---------------------------------------------------------------- 터널로 들어와 안쪽 손님 서버로 가는 새 연결
RE_PROJ = re.compile(r"^(?P<ts>\S+) \S+ kernel: (?:\[[\d. ]+\] )?(?P<prefix>\S+) .*?SRC=(?P<src>\S+) DST=(?P<dst>\S+) .*?PROTO=(?P<proto>\S+)"
                     r"(?:.*? SPT=(?P<spt>\d+) DPT=(?P<dpt>\d+))?")


class TunnelIn:
    """터널에서 안쪽 손님 서버로 넘기는 새 연결(nft log, 접두 cfg.prefix)을 알린다. 주소 → 이름은 guest_env_dir/*.env(ADDR=)에서"""

    name = "projection"

    def __init__(self, cfg, host):
        self.host = host
        self.prefix = cfg["prefix"]
        self.env_dir = cfg.get("guest_env_dir", "/etc/guest")

    def guest_name(self, ip):
        import glob
        for f in glob.glob(os.path.join(self.env_dir, "*.env")):
            try:
                if any(l.strip() == f"ADDR={ip}" or l.startswith(f"ADDR={ip}/") for l in open(f)):
                    return os.path.basename(f)[:-4]
            except OSError:
                pass
        return ip

    def feed(self, line):
        m = RE_PROJ.match(line)
        if not m or m["prefix"] != self.prefix:
            return []
        port = f":{m['dpt']}" if m["dpt"] else ""
        return [{"host": self.host, "source": "터널", "client": m["src"] + (f":{m['spt']}" if m["spt"] else ""), "user": None,
                 "database": None, "result": f"{self.guest_name(m['dst'])}({m['dst']}{port}/{m['proto']}) 새 연결", "log_ts": m["ts"],
                 "lines": [line.split(" kernel: ", 1)[-1][:300]]}]

    def tick(self):
        return []


# ---------------------------------------------------------------- 자격증명 파일 열람·지속성 경로 변경(auditd)
RE_AUDIT = re.compile(r"^type=(?P<type>\S+) msg=audit\((?P<ts>\d+\.\d+):(?P<serial>\d+)\): (?P<body>.*)$")
RE_KV = re.compile(r'(\w+)=("[^"]*"|\S+)')


def audit_fields(body):
    raw, _, enriched = body.partition("\x1d")   # ENRICHED 형식: 뒤쪽 대문자 이름은 숫자 → 이름 풀이
    f = {k: v.strip('"') for k, v in RE_KV.findall(raw)}
    f.update({"_" + k: v.strip('"') for k, v in RE_KV.findall(enriched)})
    return f


def audit_str(v):
    """따옴표 없는 값은 16진수(공백·특수 문자가 든 이름, proctitle)"""
    if v and re.fullmatch(r"[0-9A-Fa-f]+", v) and len(v) % 2 == 0:
        try:
            return bytes.fromhex(v).replace(b"\x00", b" ").decode("utf-8", "replace").strip()
        except ValueError:
            return v
    return v


class AuditFiles:
    """auditd 기록에서 감시 키가 붙은 사건을 알린다.
    - secret-files: ~/.ssh·~/.aws 안 파일, 서비스 필수 환경 파일 열람(T1552.001·T1552.004)
    - persistence: authorized_keys·~/.ssh 만들기, /etc/ld.so.preload, cron.d·사용자 crontab 변경
    거르는 것: 규칙 적재(auditctl), 디렉터리 자체 열기(ls), sshd의 authorized_keys 읽기(접속마다 — 사전 인증), 같은 프로세스·같은 파일 반복"""

    name = "audit"
    PERSIST_NAMES = re.compile(r"(?:/\.ssh/authorized_keys2?|^/etc/ld\.so\.preload|^/etc/cron\.d/.+|^/var/spool/cron/crontabs/.+)$")

    def __init__(self, cfg, host):
        self.host = host
        self.keys = cfg.get("keys", {"secret-files": "자격증명 파일 열람", "persistence": "지속성 경로 변경"})
        self.skip_exe = set(cfg.get("skip_exe", ["/usr/sbin/sshd", "/usr/sbin/auditctl"]))
        self.window = float(cfg.get("dedupe_seconds", 30))
        self.ev = {}        # serial → {ts, syscall, paths, cwd, title, last}
        self.seen = {}      # (pid, key, path) → 시각

    def feed(self, line):
        m = RE_AUDIT.match(line)
        if not m:
            return []
        t, serial, f = m["type"], m["serial"], audit_fields(m["body"])
        e = self.ev.get(serial)
        if t == "SYSCALL":
            key = f.get("key", "")
            if key not in self.keys:
                return []
            self.ev[serial] = {"ts": float(m["ts"]), "sc": f, "paths": [], "cwd": None, "title": None, "last": time.monotonic()}
            return []
        if e is None:
            return []
        e["last"] = time.monotonic()
        if t == "CWD":
            e["cwd"] = audit_str(f.get("cwd"))
        elif t == "PATH":
            e["paths"].append(f)
        elif t == "PROCTITLE":
            e["title"] = audit_str(f.get("proctitle"))
            return self._finish(serial)
        elif t == "EOE":
            return self._finish(serial)
        return []

    def tick(self):
        now = time.monotonic()
        for k in [k for k, t in self.seen.items() if now - t > self.window]:
            del self.seen[k]
        out = []
        for serial in [s for s, e in self.ev.items() if now - e["last"] > 1]:
            out += self._finish(serial)
        return out

    def _finish(self, serial):
        e = self.ev.pop(serial, None)
        if not e:
            return []
        sc = e["sc"]
        key, exe, comm = sc["key"], audit_str(sc.get("exe", "")), audit_str(sc.get("comm", ""))
        if exe in self.skip_exe:
            return []
        names = []
        for p in e["paths"]:
            n = audit_str(p.get("name", ""))
            if not n or p.get("nametype") == "PARENT" or p.get("mode", "").startswith("04"):   # 디렉터리 자체
                if not (key == "persistence" and p.get("nametype") == "CREATE" and n.endswith("/.ssh")):
                    continue
            if not n.startswith("/") and e["cwd"]:
                n = os.path.normpath(os.path.join(e["cwd"], n))
            if key == "persistence" and not (self.PERSIST_NAMES.search(n) or (p.get("nametype") == "CREATE" and n.endswith("/.ssh"))):
                continue
            names.append((n, p.get("nametype", "")))
        if not names:
            return []
        pid, now = sc.get("pid"), time.monotonic()
        new = [(n, nt) for n, nt in names if (pid, key, n) not in self.seen]
        for n, _ in names:
            self.seen[(pid, key, n)] = now
        if not new:
            return []
        auid = sc.get("_AUID") or sc.get("auid")
        user = sc.get("_UID") or sc.get("uid")
        what = ", ".join(n + (f"({nt})" if nt not in ("NORMAL", "") else "") for n, nt in new)
        ok = "" if sc.get("success", "yes") == "yes" else " 실패"
        return [{"host": self.host, "source": "감사", "client": f"{comm}[{pid}] ppid {sc.get('ppid')}",
                 "user": user, "database": None, "result": f"{self.keys[key]}{ok}: {what}",
                 "log_ts": datetime.fromtimestamp(e["ts"]).astimezone().isoformat(timespec="milliseconds"),
                 "audit": {"key": key, "pid": pid, "ppid": sc.get("ppid"), "auid": auid, "ses": sc.get("ses"),
                           "uid": user, "exe": exe, "cmd": (e["title"] or "")[:300], "paths": [n for n, _ in new]},
                 "lines": [f"{exe} {e['title'] or ''}"[:300]]}]


WATCHERS = {"postgresql": PgConnections, "ports": ForwardedPorts, "gate": PayloadGate, "sshd": SshSessions, "projection": TunnelIn, "audit": AuditFiles}


def load_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def save_state(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def run(cfg, once=False):
    host = cfg.get("hostname") or socket.gethostname()
    notifier = Notifier(cfg)
    state_path = cfg.get("state_file", "/var/lib/moa-notify/state.json")
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    state = load_state(state_path)
    watches = []
    for name in set(WATCHERS) - set(cfg.get("watch", {})):   # 설정에서 빠진 감시가 남긴 커널 규칙도 정리
        if hasattr(WATCHERS[name], "teardown"):
            WATCHERS[name].teardown({})
    for name, wcfg in cfg.get("watch", {}).items():
        if not wcfg.get("enabled", True):
            if hasattr(WATCHERS.get(name), "teardown"):   # 꺼진 감시가 남긴 커널 규칙 정리
                WATCHERS[name].teardown(wcfg)
            continue
        watches.append((Follower(wcfg["path"], state, name) if wcfg.get("path") else None, WATCHERS[name](wcfg, host)))
    if not watches:
        log.info("켜진 감시 항목 없음")
    log.info("시작: %s", ", ".join(w.name for _, w in watches) or "-")
    interval = float(cfg.get("poll_seconds", 0.5))
    last_save = 0
    while True:
        for follower, watcher in watches:
            events = []
            for line in (follower.lines() if follower else []):
                events += watcher.feed(line)
            events += watcher.tick()
            for ev in events:
                ev["notified_at"] = datetime.now().astimezone().isoformat(timespec="milliseconds")
                log.info("알림: %s", json.dumps({k: v for k, v in ev.items() if k != "lines"}, ensure_ascii=False))
                notifier.send(ev)
        if time.monotonic() - last_save > 5:
            save_state(state_path, state)
            last_save = time.monotonic()
        if once:
            save_state(state_path, state)
            return
        time.sleep(interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="/etc/moa-notify/config.json")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(levelname)s %(message)s")
    with open(args.config) as f:
        cfg = json.load(f)
    run(cfg)


if __name__ == "__main__":
    main()
