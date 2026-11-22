#!/usr/bin/env python3
"""PG 바깥 응답(E2): SSLRequest 응답과, 없는 계정으로 SCRAM 로그인을 끝까지 했을 때의 오류 필드.
표준 라이브러리만 쓴다(측정하는 쪽에 psql이 없어도 됨).  python3 -I validation/pgprobe.py <주소> <포트>
"""
import base64, hashlib, hmac, os, socket, struct, sys

host, port = sys.argv[1], int(sys.argv[2])
USER = "nobody_check"


def recv_msg(s):
    hdr = b""
    while len(hdr) < 5:
        c = s.recv(5 - len(hdr))
        if not c:
            raise EOFError
        hdr += c
    t, n = hdr[:1], struct.unpack("!I", hdr[1:])[0]
    body = b""
    while len(body) < n - 4:
        body += s.recv(n - 4 - len(body))
    return t, body


def fields(body):
    out = {}
    for part in body.split(b"\0"):
        if part:
            out[chr(part[0])] = part[1:].decode(errors="replace")
    return out


s = socket.create_connection((host, port), timeout=5)
s.sendall(struct.pack("!II", 8, 80877103))
print("ssl_request:", s.recv(1).decode())
s.close()

s = socket.create_connection((host, port), timeout=5)
params = b"user\0" + USER.encode() + b"\0database\0postgres\0\0"
s.sendall(struct.pack("!II", 8 + len(params), 196608) + params)
t, body = recv_msg(s)
code = struct.unpack("!I", body[:4])[0] if t == b"R" else None
print("auth_request:", t.decode(), code, body[4:].split(b"\0")[0].decode(errors="replace") if code == 10 else "")
if code == 10:  # SASL → SCRAM-SHA-256, 틀린 비밀번호로 끝까지
    nonce = base64.b64encode(os.urandom(18)).decode()
    first_bare = f"n=,r={nonce}"
    msg = b"SCRAM-SHA-256\0" + struct.pack("!I", len("n,," + first_bare)) + ("n,," + first_bare).encode()
    s.sendall(b"p" + struct.pack("!I", 4 + len(msg)) + msg)
    t, body = recv_msg(s)
    sf = body[4:].decode()
    a = dict(kv.split("=", 1) for kv in sf.split(","))
    salted = hashlib.pbkdf2_hmac("sha256", b"x", base64.b64decode(a["s"]), int(a["i"]))
    ck = hmac.new(salted, b"Client Key", "sha256").digest()
    final_wo = f"c=biws,r={a['r']}"
    auth = f"{first_bare},{sf},{final_wo}".encode()
    sig = hmac.new(hashlib.sha256(ck).digest(), auth, "sha256").digest()
    proof = base64.b64encode(bytes(x ^ y for x, y in zip(ck, sig))).decode()
    m = f"{final_wo},p={proof}".encode()
    s.sendall(b"p" + struct.pack("!I", 4 + len(m)) + m)
    print("scram_iterations:", a["i"])
    t, body = recv_msg(s)
if t == b"E":
    f = fields(body)
    print("error:", f.get("S"), f.get("C"), f.get("M"), "| routine:", f.get("R"), "| file:", f.get("F"))
else:
    print("unexpected:", t, body[:80])
