#!/usr/bin/env python3
# Incident collection (stdin-run, root). Arguments come in on stdin too (a sys.argv line first), so ps shows only `python3 -`:
#   sock <ip> <port> <follow_s>   find the process owning the TCP socket <ip>:<port> (local side)
#   pid <pid>[,<ppid>] <follow_s> [<ses>]   start from a known process (first alive; else a live process of the session)
# Writes JSON lines to stdout: self, target, snapshot, act..., end. Nothing is written to disk.
# Reads with O_NOATIME so access times of what it reads stay as they were.
import json
import os
import socket
import struct
import subprocess
import sys
import time
import hashlib

T0 = time.time()
NOATIME = getattr(os, "O_NOATIME", 0)


def out(kind, **kw):
    kw.update(kind=kind, t=round(time.time(), 3))
    sys.stdout.write(json.dumps(kw, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def rd(path, limit=1 << 20):
    try:
        fd = os.open(path, os.O_RDONLY | NOATIME)
    except PermissionError:
        fd = os.open(path, os.O_RDONLY)
    try:
        return os.read(fd, limit)
    finally:
        os.close(fd)


def rds(path, limit=1 << 20):
    try:
        return rd(path, limit).decode("utf-8", "replace")
    except OSError:
        return None


# ---------- processes ----------
def stat_of(pid):
    s = rds(f"/proc/{pid}/stat")
    if not s:
        return None
    comm = s[s.index("(") + 1:s.rindex(")")]
    f = s[s.rindex(")") + 2:].split()
    return {"comm": comm, "state": f[0], "ppid": int(f[1]), "start_ticks": int(f[19])}


BOOT = None
for line in (rds("/proc/stat") or "").splitlines():
    if line.startswith("btime "):
        BOOT = int(line.split()[1])
HZ = os.sysconf("SC_CLK_TCK")


def started(st):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(BOOT + st["start_ticks"] / HZ)) if BOOT else None


def uid_of(pid):
    for line in (rds(f"/proc/{pid}/status") or "").splitlines():
        if line.startswith("Uid:"):
            return int(line.split()[1])


def user(uid):
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except Exception:
        return str(uid)


def cmdline(pid):
    b = None
    try:
        b = rd(f"/proc/{pid}/cmdline")
    except OSError:
        pass
    return [a.decode("utf-8", "replace") for a in b.split(b"\0") if a] if b else []


def proc(pid, deep=False):
    st = stat_of(pid)
    if not st:
        return None
    uid = uid_of(pid)
    p = {"pid": pid, "ppid": st["ppid"], "comm": st["comm"], "cmd": cmdline(pid), "user": user(uid) if uid is not None else None,
         "started": started(st), "auid": rds(f"/proc/{pid}/loginuid"), "ses": rds(f"/proc/{pid}/sessionid")}
    try:
        p["exe"] = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        p["exe"] = None
    if deep:
        try:
            p["cwd"] = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            pass
        if p["exe"]:
            try:
                p["exe_sha256"] = hashlib.sha256(rd(f"/proc/{pid}/exe", 256 << 20)).hexdigest()
            except OSError:
                pass
        env = rd(f"/proc/{pid}/environ") if os.path.exists(f"/proc/{pid}/environ") else b""
        p["env"] = [e.decode("utf-8", "replace") for e in env.split(b"\0") if e]
        fds = []
        try:
            for fd in sorted(os.listdir(f"/proc/{pid}/fd"), key=int):
                try:
                    fds.append(f"{fd} {os.readlink(f'/proc/{pid}/fd/{fd}')}")
                except OSError:
                    pass
        except OSError:
            pass
        p["fds"] = fds
    return p


def all_pids():
    return [int(d) for d in os.listdir("/proc") if d.isdigit()]


def chain(pid):
    c, seen = [], set()
    while pid and pid not in seen:
        seen.add(pid)
        p = proc(pid, deep=True)
        if not p:
            break
        c.append(p)
        pid = p["ppid"]
    return c


# ---------- sockets ----------
TCP_STATES = {1: "ESTAB", 2: "SYN-SENT", 3: "SYN-RECV", 4: "FIN-WAIT1", 5: "FIN-WAIT2", 6: "TIME-WAIT", 7: "CLOSE",
              8: "CLOSE-WAIT", 9: "LAST-ACK", 10: "LISTEN", 11: "CLOSING"}


def addr4(h):
    ip, port = h.split(":")
    return socket.inet_ntoa(struct.pack("<I", int(ip, 16))), int(port, 16)


def addr6(h):
    ip, port = h.split(":")
    b = bytes.fromhex(ip)
    b = b"".join(b[i:i + 4][::-1] for i in range(0, 16, 4))
    a = socket.inet_ntop(socket.AF_INET6, b)
    return (a[7:] if a.startswith("::ffff:") else a), int(port, 16)


def sockets():
    res = []
    for proto, f, conv in (("tcp", "/proc/net/tcp", addr4), ("tcp6", "/proc/net/tcp6", addr6),
                           ("udp", "/proc/net/udp", addr4), ("udp6", "/proc/net/udp6", addr6)):
        for line in (rds(f) or "").splitlines()[1:]:
            c = line.split()
            l, r = conv(c[1]), conv(c[2])
            st = int(c[3], 16)
            res.append({"proto": proto, "local": f"{l[0]}:{l[1]}", "remote": f"{r[0]}:{r[1]}",
                        "state": TCP_STATES.get(st, str(st)) if proto.startswith("tcp") else str(st), "inode": int(c[9]), "uid": int(c[7])})
    return res


def inode_owners():
    own = {}
    for pid in all_pids():
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                try:
                    l = os.readlink(f"/proc/{pid}/fd/{fd}")
                except OSError:
                    continue
                if l.startswith("socket:["):
                    own.setdefault(int(l[8:-1]), set()).add(pid)
        except OSError:
            pass
    return own


# ---------- snapshot ----------
def recent_files(roots, minutes=120, cap=400):
    cut = time.time() - minutes * 60
    hits = []

    def walk(d, depth):
        if depth > 6 or len(hits) >= cap:
            return
        try:
            fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY | NOATIME)
        except OSError:
            return
        try:
            with os.scandir(fd) as it:
                ents = list(it)
        except OSError:
            ents = []
        finally:
            os.close(fd)
        if any(e.name == "PG_VERSION" for e in ents):   # database cluster: changes all the time, not evidence
            return
        for e in ents:
            p = os.path.join(d, e.name)
            try:
                s = os.lstat(p)
            except OSError:
                continue
            if max(s.st_mtime, s.st_ctime) >= cut:
                hits.append({"path": p, "mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(s.st_mtime)),
                             "ctime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(s.st_ctime)), "size": s.st_size,
                             "uid": s.st_uid, "mode": oct(s.st_mode)})
            if e.is_dir(follow_symlinks=False):
                walk(p, depth + 1)

    for r in roots:
        walk(r, 0)
    return hits[:cap]


def homes():
    hs = set()
    for line in (rds("/etc/passwd") or "").splitlines():
        f = line.split(":")
        if len(f) > 6 and os.path.isdir(f[5]) and f[5] not in ("/", "/nonexistent", "/bin", "/dev", "/usr/sbin"):
            hs.add((f[0], f[5]))
    return sorted(hs)


def histories():
    res = []
    for u, h in homes():
        for n in (".bash_history", ".zsh_history", ".python_history", ".psql_history", ".mysql_history", ".lesshst", ".viminfo"):
            p = os.path.join(h, n)
            if os.path.isfile(p):
                s = os.stat(p)
                txt = rds(p, 1 << 18) or ""
                res.append({"user": u, "path": p, "mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(s.st_mtime)),
                            "lines": len(txt.splitlines()), "tail": txt.splitlines()[-60:]})
    return res


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.splitlines()
    except Exception as e:
        return [f"! {e}"]


def logins():
    auth = []
    for line in (rds("/var/log/auth.log", 1 << 22) or "").splitlines():
        if "sshd[" in line and ("Accepted " in line or "Failed " in line or "session opened" in line):
            auth.append(line)
    return {"last": run(["last", "-F", "-w", "-n", "30"]), "who": run(["who", "-a"]), "auth_log": auth[-40:]}


# ---------- follow ----------
def audit_tail(f, pos):
    f.seek(pos)
    data = f.read()
    return data, f.tell()


def hexarg(v):
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    try:
        return bytes.fromhex(v).decode("utf-8", "replace")
    except ValueError:
        return v


def parse_audit(chunk, ses, pend):
    """EXECVE of the session -> (serial, argv, pid, ppid, cwd). pend keeps partial events across reads."""
    done = []
    for line in chunk.splitlines():
        i = line.find("msg=audit(")
        if i < 0:
            continue
        serial = line[i + 10:line.index(")", i)]
        typ = line[5:line.index(" ")] if line.startswith("type=") else ""
        ev = pend.setdefault(serial, {})
        kv = {}
        for tok in line[line.index("):", i) + 2:].split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                kv[k] = v
        if typ == "SYSCALL":
            ev.update(ses=kv.get("ses"), pid=kv.get("pid"), ppid=kv.get("ppid"), uid=kv.get("uid"), exe=kv.get("exe", "").strip('"'))
        elif typ == "EXECVE":
            n = int(kv.get("argc", "0"))
            ev["argv"] = [hexarg(kv.get(f"a{j}", "")) for j in range(n)]
        elif typ == "CWD":
            ev["cwd"] = hexarg(kv.get("cwd", ""))
        elif typ == "EOE" or typ == "PROCTITLE":
            if "argv" in ev and (ev.get("ses") == ses if ses is not None else ev.get("ses") not in (None, "4294967295")):
                done.append(dict(ev, serial=serial))
            pend.pop(serial, None)
    if len(pend) > 2000:
        pend.clear()
    return done


def follow(anchor, ses, seconds):
    """Vendor: 'log activities performed by process P'. With a login session: audit execve of that session.
    Without one (e.g. a shell from a web process): poll descendants of the anchor."""
    end = time.time() + seconds
    if ses and ses not in ("4294967295", "-1"):
        out("follow", how="audit-session", ses=ses, seconds=seconds)
        try:
            f = open("/var/log/audit/audit.log", "r", errors="replace")
        except OSError as e:
            out("follow-error", error=str(e))
            return
        # start a little before T0 so the commands right before the alert are included
        pos, pend = 0, {}
        size = os.fstat(f.fileno()).st_size
        pos = max(0, size - (2 << 20))
        first = True
        rest, gone_at = "", None
        while time.time() < end:
            chunk, pos = audit_tail(f, pos)
            chunk = rest + chunk
            cut = chunk.rfind("\n") + 1   # keep a half-written last line for the next read
            chunk, rest = chunk[:cut], chunk[cut:]
            for ev in parse_audit(chunk, ses, pend):
                ts = float(ev["serial"].split(":")[0])
                if first and ts < T0 - 600:
                    continue
                out("act", src="audit", at=ts, pid=ev.get("pid"), ppid=ev.get("ppid"), uid=ev.get("uid"), exe=ev.get("exe"),
                    argv=ev.get("argv"), cwd=ev.get("cwd"))
            first = False
            if gone_at is None and not os.path.exists(f"/proc/{anchor}") and not any(
                    (rds(f"/proc/{p}/sessionid") or "") == ses for p in all_pids()):
                gone_at = time.time()
                end = min(end, gone_at + 2)   # drain what auditd writes after the session ends
            time.sleep(1)
        if gone_at:
            out("follow-stop", why="session gone")
            return
    else:
        out("follow", how="descendants", anchor=anchor, seconds=seconds)
        tracked, seen = {anchor}, set()
        while time.time() < end:
            ps = {}
            for pid in all_pids():
                st = stat_of(pid)
                if st:
                    ps[pid] = st
            grew = True
            while grew:
                grew = False
                for pid, st in ps.items():
                    if pid not in tracked and st["ppid"] in tracked:
                        tracked.add(pid)
                        grew = True
            for pid in sorted(tracked - seen):
                if pid in ps and pid != anchor:
                    p = proc(pid)
                    if p:
                        out("act", src="poll", pid=pid, ppid=p["ppid"], user=p["user"], exe=p["exe"], argv=p["cmd"], started=p["started"])
                seen.add(pid)
            if anchor not in ps:
                out("follow-stop", why="anchor gone")
                return
            time.sleep(0.5)
    out("follow-stop", why="time")


SHELLS = {"sh", "bash", "dash", "zsh", "ksh", "fish", "ash", "busybox"}


def names_for(ip):
    """Names this host would resolve to ip without asking DNS: /etc/hosts and every account's ssh config Host -> HostName."""
    names = {ip}
    for line in (rds("/etc/hosts") or "").splitlines():
        f = line.split("#")[0].split()
        if f and f[0] == ip:
            names.update(f[1:])
    for _, h in homes():
        host = []
        for line in (rds(os.path.join(h, ".ssh", "config")) or "").splitlines():
            f = line.strip().split()
            if len(f) >= 2 and f[0].lower() == "host":
                host = f[1:]
            elif len(f) >= 2 and f[0].lower() == "hostname" and (f[1] == ip or f[1] in names):
                names.update(x for x in host if not any(c in x for c in "*?!"))
    return names


def recover(dst, since):
    """The connection is already gone (fast failure). Look back in the audit log for a login-session command that named the
    destination (address or a local name for it) since `since` — the latest one is P, and its session is still followable."""
    names = names_for(dst)
    try:
        data = rd("/var/log/audit/audit.log", 8 << 20).decode("utf-8", "replace")
    except OSError:
        return None, names
    pend, hits = {}, []
    for ev in parse_audit(data, None, pend):
        ts = float(ev["serial"].split(":")[0])
        if ts < since or not ev.get("argv"):
            continue
        toks = set()
        for a in ev["argv"][1:]:
            toks.update(t for t in a.replace("@", " ").replace(":", " ").replace("/", " ").split())
        if toks & names:
            hits.append(dict(ev, at=ts))
    return (hits[-1] if hits else None), names


def main():
    a = sys.argv[1:]
    mode = a[0]
    out("self", pid=os.getpid(), ppid=os.getppid(), host=socket.gethostname())
    target, sock = None, None
    recovered = None
    if mode == "sock":   # sock <ip> <port> <follow_s> [<dst_ip> <lookback_s>]  (lookback on this host's clock — clocks differ)
        ip, port, secs = a[1], int(a[2]), int(a[3])
        want = f"{ip}:{port}"
        own = inode_owners()
        for s in sockets():
            if s["local"] == want and s["proto"].startswith("tcp"):
                sock = s
                pids = sorted(own.get(s["inode"], ()))
                if pids:
                    target = pids[0]
                    sock["pids"] = pids
                break
        out("socket", want=want, found=sock)
        if not target and len(a) > 5:
            ev, names = recover(a[4], T0 - float(a[5]))
            out("recover", dst=a[4], names=sorted(names), found=ev)
            if ev:
                recovered = ev
                live = [(p["comm"] not in SHELLS, p["pid"]) for p in (proc(x) for x in all_pids()) if p and (p["ses"] or "") == ev["ses"]]
                target = min(live)[1] if live else None
    else:   # pid[,ppid...]: the first one still alive (a short command may be gone; its parent shell usually is not)
        secs = int(a[2])
        tried = [int(x) for x in a[1].split(",") if x]
        target = next((x for x in tried if os.path.exists(f"/proc/{x}")), None)
        ses = a[3] if len(a) > 3 else ""
        if not target and ses and ses not in ("4294967295", "-1"):
            # all gone (e.g. `$(grep ...)` subshell): any live process of the same login session, a shell first
            live = [(p["comm"] not in SHELLS, p["pid"]) for p in (proc(x) for x in all_pids()) if p and (p["ses"] or "") == ses]
            target = min(live)[1] if live else None
        out("pid", tried=tried, ses=ses, alive=target)
    c = chain(target) if target else []
    anchor = None
    for p in c:   # the attacker's shell = nearest shell ancestor (or the process itself)
        if p["comm"] in SHELLS:
            anchor = p
            break
    anchor = anchor or (c[1] if len(c) > 1 else (c[0] if c else None))
    ssh_conn = None
    for p in c:
        for e in p.get("env", []):
            if e.startswith("SSH_CONNECTION="):
                ssh_conn = ssh_conn or e[15:]
    ses = ((anchor or {}).get("ses") or "").strip()
    if recovered and not ses:
        ses = recovered["ses"]
    out("target", pid=target, alive=bool(c), chain=c, anchor=anchor and anchor["pid"], ses=ses, ssh_connection=ssh_conn, recovered=recovered,
        latency=round(time.time() - T0, 3))
    own = inode_owners()
    socks = sockets()
    for s in socks:
        s["pids"] = sorted(own.get(s["inode"], ()))
    procs = [p for p in (proc(pid) for pid in sorted(all_pids())) if p]
    roots = sorted({h for _, h in homes() if h.startswith(("/home", "/root", "/srv", "/var/lib"))} |
                   {"/tmp", "/var/tmp", "/dev/shm", "/etc", "/srv", "/opt"})
    out("snapshot", processes=procs, sockets=socks, logins=logins(), recent_files=recent_files(roots), histories=histories(),
        took=round(time.time() - T0, 3))
    if anchor and secs > 0:
        follow(anchor["pid"], (anchor.get("ses") or "").strip(), secs)
    out("end", took=round(time.time() - T0, 3))


main()
