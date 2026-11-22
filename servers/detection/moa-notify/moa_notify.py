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
    """이 서버에서 쓰지 않는 포트로 온 연결을 다른 서버로 넘기고(nftables), 넘길 때마다 알린다.
    실제 프로그램이 그 포트를 쓰기 시작하면 규칙을 빼고(양보) 알린다."""

    name = "ports"

    def __init__(self, cfg, host):
        self.host = host
        self.addr = cfg["address"]
        self.prefix = cfg.get("prefix", "IN-FWD")
        self.table = cfg.get("table", "local_fwd")
        self.ports = {int(p["port"]): p["to"] for p in cfg.get("ports", [])}
        self.released = set()
        self.next_check = 0
        busy = listening_ports() & set(self.ports)
        for p in sorted(busy):  # 학습: 이미 쓰는 포트는 처음부터 넘기지 않는다
            self.released.add(p)
            log.info("포트 %d 사용 중 — 넘기지 않음", p)
        self.apply()

    def active(self):
        return {p: t for p, t in self.ports.items() if p not in self.released}

    def apply(self):
        import subprocess
        # nat 체인은 연결의 첫 패킷만 본다 → log는 연결당 한 줄
        pre = [f"    ip daddr {self.addr} tcp dport {p} log prefix \"{self.prefix} \" level info dnat to {to}"
               for p, to in sorted(self.active().items())]
        post = [f"    ip daddr {to.rsplit(':', 1)[0]} tcp dport {to.rsplit(':', 1)[1]} masquerade" for p, to in sorted(self.active().items())]
        text = (f"table ip {self.table}\ndelete table ip {self.table}\ntable ip {self.table} {{\n"
                f"  chain pre {{\n    type nat hook prerouting priority dstnat; policy accept;\n" + "\n".join(pre) + "\n  }\n"
                f"  chain post {{\n    type nat hook postrouting priority srcnat; policy accept;\n" + "\n".join(post) + "\n  }\n}\n")
        try:
            with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
                f.write("1")
        except OSError as e:
            log.warning("ip_forward: %s", e)
        r = subprocess.run(["/usr/sbin/nft", "-f", "-"], input=text, text=True, capture_output=True)
        if r.returncode:
            log.error("nft: %s", r.stderr.strip())
        else:
            log.info("넘기는 포트: %s", ", ".join(str(p) for p in sorted(self.active())) or "-")

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
        busy = listening_ports() & set(self.active())
        if not busy:
            return []
        self.released |= busy
        self.apply()
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        return [{"host": self.host, "source": "포트", "client": "-", "user": None, "database": None,
                 "result": f"{p} 실제 프로그램이 사용 시작 → 넘기기 중단", "log_ts": ts, "lines": []} for p in sorted(busy)]


# ---------------------------------------------------------------- 알림 보내기
class Notifier:
    def __init__(self, cfg):
        self.url = cfg["webhook_url"]
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
        req = urllib.request.Request(self.url, data=body, headers={
            "Content-Type": "application/json", "User-Agent": "moa-notify/1.0"})
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
WATCHERS = {"postgresql": PgConnections, "ports": ForwardedPorts}


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
    for name, wcfg in cfg.get("watch", {}).items():
        if not wcfg.get("enabled", True):
            continue
        watches.append((Follower(wcfg["path"], state, name), WATCHERS[name](wcfg, host)))
    if not watches:
        log.info("켜진 감시 항목 없음")
    log.info("시작: %s", ", ".join(w.name for _, w in watches) or "-")
    interval = float(cfg.get("poll_seconds", 0.5))
    last_save = 0
    while True:
        for follower, watcher in watches:
            events = []
            for line in follower.lines():
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
