#!/usr/bin/env python3
"""로컬 VM용 apt 캐싱 프록시(호스트에서, 표준 라이브러리만). VM은 http://10.0.2.2:3142 로 쓴다.
  python3 infra/local-vm/apt_cache.py [포트] [캐시 디렉터리]
.deb·.udeb·.tar.xz처럼 이름이 바뀌지 않는 파일만 디스크에 캐시하고, 목록(InRelease·Packages 등)은 그대로 통과시킨다.
HTTPS(CONNECT)는 다루지 않는다 — Ubuntu 기본 저장소(archive·security)는 http
로컬 전용: AWS 서버엔 쓰지 않는다(VM의 apt 프록시 설정은 lab.sh가 로컬에만 둠)
"""
import hashlib
import http.server
import os
import shutil
import socketserver
import sys
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 3142
CACHE = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser("~/.cache/deceptive2-vm/apt-cache")
IMMUTABLE = (".deb", ".udeb", ".tar.xz", ".tar.gz", ".dsc")
os.makedirs(CACHE, exist_ok=True)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        pass

    def do_GET(self):
        url = self.path
        if not url.startswith("http://"):
            self.send_error(400, "absolute http URL only")
            return
        key = os.path.join(CACHE, hashlib.sha256(url.encode()).hexdigest())
        cacheable = url.split("?")[0].endswith(IMMUTABLE)
        if cacheable and os.path.exists(key):
            self.send_response(200)
            self.send_header("Content-Length", str(os.path.getsize(key)))
            self.end_headers()
            with open(key, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
            return
        try:
            req = urllib.request.Request(url, headers={k: v for k, v in self.headers.items() if k.lower() not in ("host", "proxy-connection")})
            with urllib.request.urlopen(req, timeout=60) as r:
                self.send_response(r.status)
                for k, v in r.getheaders():
                    if k.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(k, v)
                self.end_headers()
                tmp = key + ".part"
                out = open(tmp, "wb") if cacheable else None
                while True:
                    b = r.read(1 << 16)
                    if not b:
                        break
                    self.wfile.write(b)
                    if out:
                        out.write(b)
                if out:
                    out.close()
                    os.replace(tmp, key)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
        except Exception as e:  # 네트워크 오류
            self.send_error(502, str(e)[:100])

    do_HEAD = do_GET


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    Server(("127.0.0.1", PORT), Handler).serve_forever()
