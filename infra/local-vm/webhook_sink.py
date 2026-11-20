#!/usr/bin/env python3
"""로컬 테스트용 웹훅 수신기. 받은 본문을 받은 시각과 함께 JSON 줄로 저장한다.
VM 안에서는 http://10.0.2.2:<port>/ 로 보인다(QEMU user 네트워크).
  python3 infra/local-vm/webhook_sink.py --port 9099 --out ~/.cache/deceptive2-vm/webhook.jsonl
"""
import argparse
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=9099)
ap.add_argument("--out", required=True)
args = ap.parse_args()


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        rec = {"received_at": datetime.now().astimezone().isoformat(timespec="milliseconds")}
        try:
            rec["body"] = json.loads(body)
        except ValueError:
            rec["raw"] = body.decode("utf-8", "replace")
        with open(args.out, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


HTTPServer(("127.0.0.1", args.port), H).serve_forever()
