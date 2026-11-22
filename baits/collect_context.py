#!/usr/bin/env python3
"""서버의 맥락을 읽기 전용으로 모아 JSON 한 줄로 낸다. Ansible `script` 모듈로 실행되고 서버에 남지 않는다.
비밀값은 읽지 않는다: 환경 파일은 변수 이름과 "값이 비었는지/어떤 형식인지"만, 자격증명 파일은 섹션 이름만.
(관리 쪽 코드지만 서버에서 실행되므로 이름·문자열에 프로젝트 용어를 쓰지 않는다)
"""
import glob
import json
import os
import pwd
import re
import shutil
import socket
import subprocess
from urllib.parse import urlsplit


def run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ""


def mtime(p):
    try:
        return int(os.lstat(p).st_mtime)
    except OSError:
        return None


def env_shape(path):
    """KEY=VALUE 파일에서 이름과 값의 모양만(값 자체는 내보내지 않음)."""
    keys = []
    try:
        lines = open(path, errors="replace").read().splitlines()
    except OSError:
        return None
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        shape = {"key": k, "line": i, "empty": v == ""}
        if "://" in v:
            u = urlsplit(v)
            shape.update(scheme=u.scheme, host=u.hostname or "", port=u.port, db=(u.path or "").lstrip("/"))
        keys.append(shape)
    comments = [i for i, l in enumerate(lines) if l.startswith("#")]
    return {"path": path, "keys": keys, "nlines": len(lines), "comment_lines": comments, "mtime": mtime(path)}


def services():
    out = []
    names = run("systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--plain").split()
    for name in [n for n in names if n.endswith(".service")]:
        prop = run("systemctl", "show", name, "-p", "EnvironmentFiles", "-p", "User", "-p", "ExecStart", "-p", "FragmentPath")
        envs = re.findall(r"EnvironmentFiles=(\S+)", prop)
        user = (re.search(r"^User=(.*)$", prop, re.M) or [None, ""])[1]
        if not envs:
            continue
        out.append({"name": name, "user": user, "env_files": [e for e in (env_shape(p) for p in envs) if e]})
    return out


def ssh_config_shape(path):
    if not os.path.exists(path):
        return None
    txt = open(path, errors="replace").read()
    return {"path": path, "hosts": re.findall(r"^\s*Host\s+(.+)$", txt, re.M),
            "identity_files": re.findall(r"^\s*IdentityFile\s+(\S+)", txt, re.M),
            "indent": (re.search(r"^(\s+)\S", txt, re.M) or [None, "    "])[1], "mtime": mtime(path)}


def cron_uses(cron, word):
    """주석이 아닌 cron 줄 또는 그 줄이 부르는 스크립트 안에 word가 있는가(스크립트 이름만 보면 놓친다 — 11/22)"""
    pat = re.compile(rf"\b{re.escape(word)}\b")
    for line in cron.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if pat.search(line):
            return True
        for tok in re.findall(r"(/[\w./-]+)", line):
            try:
                if os.path.isfile(tok) and os.path.getsize(tok) < 65536 and pat.search(open(tok, errors="replace").read()):
                    return True
            except OSError:
                pass
    return False


def users():
    out = []
    for p in pwd.getpwall():
        if p.pw_shell.endswith(("nologin", "false", "sync")) or not os.path.isdir(p.pw_dir):
            continue
        # uid로 거르지 않는다: postgres처럼 셸이 있는 서비스 계정도 사람이 쓰고 cron이 돈다(11/22 놓침)
        h = p.pw_dir
        hist = os.path.join(h, ".bash_history")
        used = {}
        nhist = 0
        if os.path.exists(hist):
            lines = open(hist, errors="replace").read().splitlines()
            nhist = len(lines)
            for l in lines:
                w = l.split()[:1]
                if w:
                    used[w[0]] = used.get(w[0], 0) + 1
        aws_dir = os.path.join(h, ".aws")
        aws_profiles = []
        for f in ("credentials", "config"):
            fp = os.path.join(aws_dir, f)
            if os.path.exists(fp):
                aws_profiles += re.findall(r"^\[(?:profile )?([^\]]+)\]", open(fp, errors="replace").read(), re.M)
        cron = run("crontab", "-l", "-u", p.pw_name)
        cron_aws = cron_uses(cron, "aws")
        out.append({
            "name": p.pw_name, "uid": p.pw_uid, "gid": p.pw_gid, "home": h, "shell": p.pw_shell,
            "home_mtime": mtime(h),
            "ssh_dir": os.path.isdir(os.path.join(h, ".ssh")), "ssh_dir_mtime": mtime(os.path.join(h, ".ssh")),
            "ssh_config": ssh_config_shape(os.path.join(h, ".ssh", "config")),
            "known_hosts": os.path.exists(os.path.join(h, ".ssh", "known_hosts")),
            "known_hosts_mtime": mtime(os.path.join(h, ".ssh", "known_hosts")),
            "keys": sorted(os.path.basename(k) for k in glob.glob(os.path.join(h, ".ssh", "id_*")) if not k.endswith(".pub")),
            "history": {"path": hist, "lines": nhist, "mtime": mtime(hist), "top": sorted(used, key=used.get, reverse=True)[:15]} if nhist else None,
            "aws": {"dir": os.path.isdir(aws_dir), "profiles": aws_profiles, "cred_mtime": mtime(os.path.join(aws_dir, "credentials"))},
            "cron_uses_aws": cron_aws,
            "agent_running": bool(run("pgrep", "-u", p.pw_name, "-x", "ssh-agent").strip()),
        })
    return out


def resolution(names):
    hosts = open("/etc/hosts", errors="replace").read()
    out = {}
    for n in names:
        try:
            ip = socket.gethostbyname(n)
        except OSError:
            ip = None
        out[n] = {"ip": ip, "in_etc_hosts": bool(re.search(rf"\s{re.escape(n)}(\s|$)", hosts, re.M))}
    return out


def main():
    svcs = services()
    hostnames = sorted({k.get("host") for s in svcs for e in s["env_files"] for k in e["keys"] if k.get("host")})
    print(json.dumps({
        "hostname": socket.gethostname(),
        "users": users(),
        "services": svcs,
        "resolution": resolution(hostnames + ["db-backup-01", "stg-01"]),
        "etc_hosts_mtime": mtime("/etc/hosts"),
        "tools": {t: bool(shutil.which(t)) for t in ("ssh", "psql", "aws", "git", "ssh-agent", "tmux")},
        "processes": sorted(set(run("ps", "-eo", "comm=").split())),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
