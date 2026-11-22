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
    print(json.dumps({"results": res}))


if __name__ == "__main__":
    main()
