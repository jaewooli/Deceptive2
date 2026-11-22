#!/usr/bin/env python3
"""서버에서 작업 목록(JSON 파일)을 적용·검사·회수한다. Ansible `script`로 실행되고 서버에 남지 않는다.
  apply_ops.py <작업 파일> apply|check|absent
작업 파일은 root 0600 임시 파일로 받는다(내용을 명령 인자로 넘기면 auditd execve 기록에 남는다 — 11/22 실측).
표시(BEGIN/END 같은 관리 주석)를 남기지 않고 정확한 줄·블록만 넣는다. 파일 시각은 지정한 값으로 되돌린다.
출력: JSON {"results": [{"i": 번호, "state": "ok|changed|drift|absent"}]}  check = 바꾸지 않고 다른지만
(서버에서 실행되므로 이름·문자열에 프로젝트 용어를 쓰지 않는다)
"""
import json
import os
import shutil

DATA = {}


def shutil_which(x):
    return shutil.which(x)
import pwd
import grp
import sys
import time


def when(s):
    return time.mktime(time.strptime(s, "%Y%m%d%H%M.%S")) if s else None


def read(p):
    try:
        return open(p, errors="surrogateescape").read()
    except FileNotFoundError:
        return None


def write(p, text, op):
    mode = int(op.get("mode", "0644"), 8) if op.get("mode") else None
    old = os.stat(p) if os.path.exists(p) else None
    tmp = p + ".tmp~"
    with open(tmp, "w", errors="surrogateescape") as f:
        f.write(text)
    if old:
        os.chown(tmp, old.st_uid, old.st_gid)
        os.chmod(tmp, mode if mode is not None else old.st_mode & 0o7777)
    os.replace(tmp, p)
    finish(p, op)


def finish(p, op):
    if op.get("owner"):
        g = op.get("group")
        gid = int(g) if g and g.isdigit() else (grp.getgrnam(g).gr_gid if g else -1)
        os.chown(p, pwd.getpwnam(op["owner"]).pw_uid, gid)
    if op.get("mode") and op["kind"] != "line":
        os.chmod(p, int(op["mode"], 8))
    t = when(op.get("mtime"))
    if t:
        os.utime(p, (t, t), follow_symlinks=False)


def do(op, mode):
    k, p = op["kind"], op.get("path")
    cur = read(p) if p and k != "dir" else None
    if k == "dir":
        exists = os.path.isdir(p)
        if mode == "absent":
            return "absent"  # 디렉터리는 원래 있었을 수 있다 — 지우지 않는다
        if exists:
            if mode == "apply":
                finish(p, op)
            return "ok"
        if mode == "check":
            return "drift"
        os.makedirs(p)
        finish(p, op)
        return "changed"
    if k == "file":
        want = op["content"]
        if mode == "absent":
            if cur is not None:
                os.remove(p)
            return "absent"
        if cur == want:
            return "ok"
        if mode == "check":
            return "drift"
        write(p, want, op) if cur is not None else (open(p, "w").write(want), finish(p, op))
        return "changed"
    if k == "line":
        import re
        lines = (cur or "").splitlines(keepends=True)
        idx = [i for i, l in enumerate(lines) if re.search(op["regexp"], l.rstrip("\n"))]
        if mode == "absent":
            if idx:
                if op.get("absent_line") is None:
                    del lines[idx[0]]
                else:
                    lines[idx[0]] = op["absent_line"] + "\n"
                write(p, "".join(lines), op)
            return "absent"
        if idx and lines[idx[0]].rstrip("\n") == op["line"]:
            return "ok"
        if mode == "check":
            return "drift"
        if idx:
            lines[idx[0]] = op["line"] + "\n"
        else:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            lines.append(op["line"] + "\n")
        write(p, "".join(lines), op)
        return "changed"
    if k == "block":
        blk = op["block"]
        if mode == "absent":
            if cur and blk in cur:
                sep = "\n" + blk
                rest = cur.replace(sep, "", 1) if sep in cur else cur.replace(blk, "", 1)
                if rest.strip():
                    write(p, rest, op)
                else:
                    os.remove(p)  # 미끼가 만든 파일이었다 — 빈 파일을 남기면 그것도 흔적(11/22)
            return "absent"
        if cur is not None and blk in cur:
            return "ok"
        if mode == "check":
            return "drift"
        text = blk if not cur else cur + ("" if cur.endswith("\n") else "\n") + "\n" + blk
        if cur is None:
            open(p, "w").write(text)
            finish(p, op)
        else:
            write(p, text, op)
        return "changed"
    if k == "insert":
        # 미끼 줄은 연속된 한 덩어리로만 찾고 넣고 뺀다. 줄 단위로 지우면 원래 히스토리의 같은 줄(exit 등)까지 지운다(11/22 실측)
        lines = (cur or "").splitlines(keepends=True)
        want = [l + "\n" for l in op["lines"]]
        n = len(want)
        pos = next((i for i in range(len(lines) - n + 1) if lines[i:i + n] == want), None)
        if mode == "absent":
            if pos is not None:
                del lines[pos:pos + n]
                write(p, "".join(lines), op)
            return "absent"
        if pos is not None:
            return "ok"
        if mode == "check":
            return "drift"
        at = int(len(lines) * op.get("ratio", 0.6))
        b = op.get("boundary")
        if b:  # 세션 중간에 끼지 않게: 그 지점 뒤의 첫 경계 줄(exit) 다음에
            nxt = [i + 1 for i in range(at, len(lines)) if lines[i].strip() == b]
            at = nxt[0] if nxt else len(lines)
        lines[at:at] = want
        write(p, "".join(lines), op)
        return "changed"
    if k == "unit":
        # systemd 서비스 미끼: 유닛·스크립트 파일은 file 작업으로 먼저 두고, 여기선 켜짐 상태만
        import subprocess
        name = op["name"]
        active = subprocess.run(["systemctl", "is-active", "--quiet", name]).returncode == 0
        enabled = subprocess.run(["systemctl", "is-enabled", "--quiet", name]).returncode == 0
        if mode == "absent":
            subprocess.run(["systemctl", "disable", "--now", name], capture_output=True)
            subprocess.run(["systemctl", "daemon-reload"])
            return "absent"
        if active and enabled:
            return "ok"
        if mode == "check":
            return "drift"
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "--now", name], check=True, capture_output=True)
        link = f"/etc/systemd/system/multi-user.target.wants/{name}"
        t = when(op.get("mtime"))
        if t and os.path.islink(link):
            os.utime(link, (t, t), follow_symlinks=False)
        return "changed"
    if k == "agent_session":
        # 잊힌 tmux 세션 안의 ssh-agent에 키를 올려 둔다. 키는 메모리에만(임시 파일은 ssh-add 뒤 바로 삭제)
        import subprocess, glob, tempfile
        user, sess, fp = op["user"], op["session"], op["fingerprint"]
        pw_ = pwd.getpwnam(user)
        def as_user(*cmd, **kw):
            return subprocess.run(["/usr/sbin/runuser", "-u", user, "--", *cmd], capture_output=True, text=True, **kw)
        def find():
            for sock in glob.glob("/tmp/ssh-*/agent.*"):
                try:
                    if os.stat(sock).st_uid != pw_.pw_uid:
                        continue
                except OSError:
                    continue
                r = subprocess.run(["/usr/sbin/runuser", "-u", user, "--", "ssh-add", "-l"], env=dict(os.environ, SSH_AUTH_SOCK=sock),
                                   capture_output=True, text=True)
                if fp in r.stdout:
                    return sock
            return None
        has_sess = as_user("tmux", "has-session", "-t", sess).returncode == 0
        sock = find()
        if mode == "absent":
            if has_sess:
                as_user("tmux", "kill-session", "-t", sess)
            subprocess.run(["pkill", "-u", user, "-x", "ssh-agent"])
            return "absent"
        if has_sess and sock:
            return "ok"
        if mode == "check":
            return "gone" if not has_sess else "drift"
        if not has_sess:
            as_user("tmux", "new-session", "-d", "-s", sess, "-x", "200", "-y", "50", cwd=pw_.pw_dir)
        # 키를 사용자 소유 0600 임시 파일로 → 세션 안에서 사람이 친 것처럼 ssh-agent·ssh-add → 파일 삭제
        fd, kp = tempfile.mkstemp(prefix=".k", dir="/tmp")
        os.write(fd, op["private"].encode()); os.close(fd)
        os.chown(kp, pw_.pw_uid, pw_.pw_gid); os.chmod(kp, 0o600)
        for line in ("cd /srv/app", "eval $(ssh-agent -s)", f"ssh-add {kp} && rm -f {kp}", "clear", "git log --oneline -3"):
            as_user("tmux", "send-keys", "-t", sess, line, "Enter")
            time.sleep(0.4)
        for _ in range(20):
            if find():
                break
            time.sleep(0.3)
        if os.path.exists(kp):
            os.remove(kp)
        return "changed" if find() else "failed"
    if k == "wg_key":
        # 터널 키(없으면 만듦) → 공개키를 돌려준다
        import subprocess
        kp = f"/etc/wireguard/{op['name']}.key"
        if mode == "absent":
            return "absent"
        if not shutil_which("wg"):
            subprocess.run(["apt-get", "install", "-y", "-q", "wireguard-tools"], env=dict(os.environ, DEBIAN_FRONTEND="noninteractive"),
                           capture_output=True, check=True)
        os.makedirs("/etc/wireguard", mode=0o700, exist_ok=True)
        if not os.path.exists(kp):
            key = subprocess.run(["wg", "genkey"], capture_output=True, text=True, check=True).stdout
            fd = os.open(kp, os.O_WRONLY | os.O_CREAT, 0o600); os.write(fd, key.encode()); os.close(fd)
        DATA[op.get("as", "pub")] = subprocess.run(["wg", "pubkey"], input=open(kp).read(), capture_output=True, text=True).stdout.strip()
        return "ok"
    if k == "run":
        # 스크립트를 임시 파일로 실행하고 지운다(서버에 남기지 않음). 인자는 공개 값만
        import subprocess, tempfile
        if mode == "check":
            return "ok"
        if mode == "absent" and not op.get("on_absent"):
            return "absent"
        argv = op["on_absent"] if mode == "absent" else op["argv"]
        fd, sp = tempfile.mkstemp(prefix=".r", dir="/root"); os.write(fd, op["script"].encode()); os.close(fd)
        try:
            r = subprocess.run(["/bin/bash", sp, *argv], capture_output=True, text=True)
        finally:
            os.remove(sp)
        for line in r.stdout.splitlines():
            if "=" in line and line.split("=", 1)[0] in op.get("collect", []):
                DATA[line.split("=", 1)[0]] = line.split("=", 1)[1].split()[0]
        if r.returncode:
            DATA["error"] = (r.stderr or r.stdout)[-800:]
            return "failed"
        return "absent" if mode == "absent" else "changed"
    if k == "ports_config":
        # 세 서버 공통 데몬 설정에서 ports 감시만 바꾼다(다른 감시·웹훅은 그대로) → 다시 시작
        import subprocess
        p = "/etc/moa-notify/config.json"
        cfg = json.load(open(p))
        w = cfg.setdefault("watch", {})
        cur = w.get("ports", {})
        want_ports = sorted(set(op["ports"]))
        same = cur.get("enabled") and sorted(int(x["port"]) for x in cur.get("ports", [])) == want_ports and cur.get("address") == op["address"]
        if mode == "check":
            try:
                st = json.load(open("/var/lib/moa-notify/ports.json"))
            except (OSError, ValueError):
                st = {}
            rel = sorted(set(st.get("released", [])) & set(want_ports))
            if rel:
                DATA["released"] = rel  # 실제 프로그램이 그 포트를 쓰기 시작해 넘기기를 멈춤 — 관리 쪽이 판단
                return "released"
            return "ok" if same or not want_ports else "drift"
        try:
            rel_now = set(json.load(open("/var/lib/moa-notify/ports.json")).get("released", [])) & set(want_ports)
        except (OSError, ValueError):
            rel_now = set()
        if same and mode == "apply" and not rel_now:
            return "ok"
        # 설정이 같아도 원하는 포트가 양보 상태면 다시 시작(관리 쪽이 다시 쓰기로 정함 — 데몬이 시작 때 비었는지 다시 확인)
        if want_ports:
            w["ports"] = {"enabled": True, "path": "/var/log/kern.log", "address": op["address"], "iface": op["iface"], "tunnel": "wg0",
                          "ports": [{"port": x} for x in want_ports]}
        else:
            w.pop("ports", None)
        tmp = p + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600); os.write(fd, json.dumps(cfg, ensure_ascii=False, indent=1).encode()); os.close(fd)
        os.replace(tmp, p)
        subprocess.run(["systemctl", "restart", "moa-notify"], check=True)
        return "changed"
    if k == "decoy_audit":
        # 옵션 없는 일반 키 중 레지스트리에 없는 것 = 고아 미끼(또는 사람이 넣은 키). 보고만 한다
        home = pwd.getpwnam(op["user"]).pw_dir
        cur = read(os.path.join(home, ".ssh", "authorized_keys")) or ""
        plain = [l for l in cur.splitlines() if l.startswith(("ssh-", "ecdsa-"))]
        return "drift" if [l for l in plain if l not in op["known"]] else "ok"
    if k == "decoy_key":
        home = pwd.getpwnam(op["user"]).pw_dir
        p = os.path.join(home, ".ssh", "authorized_keys")
        cur = read(p) or ""
        has = op["line"] in cur.splitlines()
        if mode == "absent":
            if has:
                st = os.stat(p)
                write(p, "".join(l + "\n" for l in cur.splitlines() if l != op["line"]), {"kind": k, "mtime": time.strftime("%Y%m%d%H%M.%S", time.localtime(st.st_mtime))})
            return "absent"
        if has:
            return "ok"
        if mode == "check":
            return "drift"
        st = os.stat(p) if os.path.exists(p) else None
        write(p, cur + ("" if not cur or cur.endswith("\n") else "\n") + op["line"] + "\n",
              {"kind": k, "mtime": time.strftime("%Y%m%d%H%M.%S", time.localtime(st.st_mtime)) if st else None})
        return "changed"
    raise SystemExit(f"unknown op {k}")


def main():
    path, mode = sys.argv[1], sys.argv[2]
    ops = json.load(open(path))
    os.remove(path)
    res = []
    for i, op in enumerate(ops):
        res.append({"i": i, "state": do(op, mode)})
    print(json.dumps({"results": res, "data": DATA}))


if __name__ == "__main__":
    main()
