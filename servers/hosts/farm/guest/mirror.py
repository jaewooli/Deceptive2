#!/usr/bin/env python3
"""시점 고정 apt 미러(팜) — 투영 디코이의 주기적 재블렌딩(11/23 사용자 결정).
디코이는 이웃(같은 구간 진짜 서버)처럼 자기 unattended-upgrades로 업데이트한다(재부팅 없음, 같은 흔적). 팜은 디코이의 apt 요청을 받아
**이웃과 같은 시점의 스냅숏**(snapshot.ubuntu.com)에서 돌려준다 — 디코이가 이웃보다 앞서거나 뒤처지지 않게.
  - 받는 형식: 프록시 형식(로컬: 디코이의 01-lab-proxy → 팜이 DNAT) / 일반 형식(AWS: 투명 가로채기, Host 헤더)
  - 허용: archive·security.ubuntu.com의 /ubuntu/ 경로만(GET·HEAD). 나머지는 403 — 디코이의 일반 인터넷 통로가 되지 않게
  - 시점: 출발지 주소 → /etc/guest/<이름>.env(ADDR·SNAPSHOT·SNAPSHOT_SECURITY). 보안 저장소 경로는 보안 시점, 나머지는 일반 시점
    (pool 파일은 일반 시점 → 없으면 보안 시점). 재블렌딩 = 엔진이 env의 시점 값을 바꾸는 것(요청마다 다시 읽음)
  - 요청은 모두 로그(journal) — 공격자가 디코이에서 apt를 쓰는 것도 흔적
  python3 mirror.py --bind 169.254.31.2 --port 3144 [--env-dir /etc/guest]
"""
import argparse
import glob
import http.server
import logging
import os
import re
import socket
import socketserver
import urllib.error
import urllib.request
from urllib.parse import urlsplit

logging.basicConfig(format="%(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("mirror")
HOSTS = {"archive.ubuntu.com", "security.ubuntu.com"}
SNAP = "https://snapshot.ubuntu.com/ubuntu/{ts}/{rest}"
IP_FREEBIND = 15


def env_for(ip, env_dir):
    for f in glob.glob(os.path.join(env_dir, "*.env")):
        try:
            kv = dict(l.strip().split("=", 1) for l in open(f) if "=" in l)
        except OSError:
            continue
        if kv.get("ADDR", "").split("/")[0] == ip:
            return os.path.basename(f)[:-4], kv
    return None, {}


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _target(self):
        u = urlsplit(self.path) if self.path.startswith("http://") else None
        host = (u.hostname if u else (self.headers.get("Host") or "").split(":")[0]).lower()
        path = u.path if u else self.path.split("?")[0]
        return host, path

    def _serve(self, head):
        name, kv = env_for(self.client_address[0], self.server.env_dir)
        host, path = self._target()
        if not name or host not in HOSTS or not path.startswith("/ubuntu/") or ".." in path:
            log.warning("거부 %s(%s) %s %s%s", name or "?", self.client_address[0], self.command, host, path)
            return self._reply(403, b"")
        rest = path[len("/ubuntu/"):]
        main, sec = kv.get("SNAPSHOT", ""), kv.get("SNAPSHOT_SECURITY", "") or kv.get("SNAPSHOT", "")
        if not main:
            return self._reply(404, b"")
        order = [sec] if re.search(r"^dists/[^/]+-security(/|$)", rest) else ([main, sec] if rest.startswith("pool/") else [main])
        for ts in dict.fromkeys(order):
            url = SNAP.format(ts=ts, rest=rest)
            try:
                req = urllib.request.Request(url, method="HEAD" if head else "GET", headers={"User-Agent": "Debian APT-HTTP/1.3"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    body = b"" if head else r.read()
                    log.info("%s(%s) %s %s → %s %d", name, self.client_address[0], self.command, rest, ts, r.status)
                    return self._reply(r.status, body, r.headers.get("Content-Type"), r.headers.get("Last-Modified"),
                                       length=int(r.headers.get("Content-Length", len(body))) if head else None)
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    log.warning("%s %s → %s %d", name, rest, ts, e.code)
                    return self._reply(e.code, b"")
            except OSError as e:
                log.warning("%s %s → %s 실패: %s", name, rest, ts, e)
                return self._reply(502, b"")
        log.info("%s(%s) %s %s → 없음", name, self.client_address[0], self.command, rest)
        return self._reply(404, b"")

    def _reply(self, code, body, ctype=None, lm=None, length=None):
        self.send_response(code)
        self.send_header("Content-Length", str(length if length is not None else len(body)))
        if ctype:
            self.send_header("Content-Type", ctype)
        if lm:
            self.send_header("Last-Modified", lm)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        self._serve(False)

    def do_HEAD(self):
        self._serve(True)

    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

    def server_bind(self):
        # 탭 주소(169.254.31.2)는 디코이 VM이 떠야 생긴다 — 그 전에도 묶을 수 있게(IP_FREEBIND)
        self.socket.setsockopt(socket.SOL_IP, IP_FREEBIND, 1)
        super().server_bind()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bind", default="169.254.31.2")
    ap.add_argument("--port", type=int, default=3144)
    ap.add_argument("--env-dir", default="/etc/guest")
    a = ap.parse_args()
    s = Server((a.bind, a.port), H)
    s.env_dir = a.env_dir
    log.info("시작 %s:%d", a.bind, a.port)
    s.serve_forever()


if __name__ == "__main__":
    main()
