"""미끼 유형 = 배치 규칙(맥락 조건) + 그 기계에 맞춘 내용 생성.  (Illusive 맥락 기반 배포 — 01-vendor-feature-map 문제 1)

각 유형:
  match(ctx, host)          -> 이 기계에서 미끼를 둘 수 있는 자리(anchor) 목록. 맥락이 없으면 빈 목록(억지로 두지 않음)
  new_ident(anchor, used)   -> 고유 ID(목적지에서 이 미끼를 알아보는 값). 교체 때 다시 부른다
  ops(anchor, ident, dest)  -> Ansible이 적용할 작업 목록(apply.yml). 회수는 같은 작업의 state=absent
목적지(dest): 미끼가 가리키는 디코이 주소(destinations.yml, 커밋 안 함)
"""
import random
import re
import secrets
import string
import subprocess
import tempfile
import time
from datetime import datetime

DECOY = "db-backup-01"


def ts(epoch):
    return datetime.fromtimestamp(epoch).strftime("%Y%m%d%H%M.%S") if epoch else None


def pw(n=20):
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(n))


def shell_users(ctx):
    return list(ctx["users"])  # 수집기가 셸 있는 계정만 준다(서비스 계정 포함)


# ------------------------------------------------------------------ T1형: 설정 파일의 꺼진 기능 DB URL
class EnvDbUrl:
    name = "env_db_url"
    # 변수 접두사 → 그 기능에 어울리는 읽기 전용 DB 계정 이름 후보(교체 때 다음 것)
    POOL = {"REPORT": ["report_ro", "report_reader", "rpt_ro", "report_svc"]}

    def match(self, ctx, host):
        out = []
        for svc in ctx["services"]:
            for ef in svc["env_files"]:
                keys = {k["key"]: k for k in ef["keys"]}
                main = keys.get("DATABASE_URL")
                if not main or not main.get("scheme", "").startswith("postgresql"):
                    continue  # 앱이 PostgreSQL을 쓰지 않으면 PG 미끼는 어색하다
                for k in ef["keys"]:
                    m = re.match(r"^([A-Z]+)_DB_URL$", k["key"])
                    # 비어 있는 "꺼진 기능"의 DB 주소 — 채워 두면 남은 설정처럼 보인다.
                    # 이미 디코이를 가리키면 내 미끼가 차지한 같은 자리(맥락이 사라진 게 아님 — 11/22 오판)
                    if m and (k["empty"] or k.get("host") == DECOY):
                        out.append({"path": ef["path"], "key": k["key"], "prefix": m.group(1), "service": svc["name"],
                                    "owner": svc["user"], "scheme": main["scheme"], "db": main.get("db") or "postgres",
                                    "main_host_in_etc_hosts": ctx["resolution"].get(main.get("host"), {}).get("in_etc_hosts", False),
                                    "decoy_resolves": bool(ctx["resolution"].get(DECOY, {}).get("ip")),
                                    "file_mtime": ef["mtime"], "etc_hosts_mtime": ctx["etc_hosts_mtime"]})
        return out

    def new_ident(self, a, used):
        pool = self.POOL.get(a["prefix"], [f"{a['prefix'].lower()}_ro", f"{a['prefix'].lower()}_reader"])
        for n in pool:
            if n not in used:
                return {"kind": "db_user", "value": n, "password": pw()}
        return {"kind": "db_user", "value": f"{pool[0]}_{secrets.token_hex(2)}", "password": pw()}

    def ops(self, a, ident, dest):
        url = f"{a['scheme']}://{ident['value']}:{ident['password']}@{DECOY}:5432/{a['db']}"
        o = [{"kind": "line", "path": a["path"], "regexp": f"^{a['key']}=", "line": f"{a['key']}={url}",
              "absent_line": f"{a['key']}=", "mtime": ts(a["file_mtime"])}]
        # 이 서버가 다른 서버 이름을 /etc/hosts로 찾는다면 디코이 이름도 같은 방식으로(연결 흔적 C3)
        if a["main_host_in_etc_hosts"] and not a["decoy_resolves"]:
            o.append({"kind": "line", "path": "/etc/hosts", "regexp": rf"\s{DECOY}$", "line": f"{dest['ip']} {DECOY}",
                      "absent_line": None, "mtime": ts(a["etc_hosts_mtime"])})
        return o


# ------------------------------------------------------------------ T2형: ~/.ssh/config + 키 / T3형: 히스토리
def hashed_known_host(names, pubkey):
    """ssh-keygen -H 형식(|1|salt|hmac) — Ubuntu 기본 HashKnownHosts yes와 같은 모양"""
    import base64, hashlib, hmac, os as _os
    out = []
    for n in names:
        salt = _os.urandom(20)
        mac = hmac.new(salt, n.encode(), hashlib.sha1).digest()
        out.append(f"|1|{base64.b64encode(salt).decode()}|{base64.b64encode(mac).decode()} {pubkey}")
    return out


def keygen(comment):
    with tempfile.TemporaryDirectory() as t:
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", f"{t}/k"], check=True)
        priv, pub = open(f"{t}/k").read(), open(f"{t}/k.pub").read().strip()
        fp = subprocess.run(["ssh-keygen", "-lf", f"{t}/k.pub"], capture_output=True, text=True).stdout.split()[1]
    return priv, pub, fp


class SshConfig:
    name = "ssh_config"

    def match(self, ctx, host):
        out = []
        for u in shell_users(ctx):
            if u["name"] == "root":
                continue
            # 나가는 ssh를 쓰는 흔적만 센다. ~/.ssh에 authorized_keys만 있으면 "들어오는" 계정일 뿐(11/22: ubuntu 오판)
            uses_ssh = (u["known_hosts"] or u["keys"] or u["ssh_config"]
                        or (u["history"] and any(c in u["history"]["top"] for c in ("ssh", "scp", "rsync"))))
            if uses_ssh:  # 이미 디코이 Host가 있으면 내 미끼 자리 — 같은 자리로 낸다
                ids = (u["ssh_config"] or {}).get("identity_files", []) + u["keys"]
                keyname = "id_ed25519_backup" if any(k.startswith("id_") for k in ids) or not ids else "backup_ed25519"
                out.append({"user": u["name"], "home": u["home"], "uid": u["uid"], "gid": u["gid"], "keyname": keyname,
                            "indent": (u["ssh_config"] or {}).get("indent", "    "),
                            "config_mtime": (u["ssh_config"] or {}).get("mtime"), "ssh_dir_mtime": u["ssh_dir_mtime"],
                            "known_hosts_mtime": u.get("known_hosts_mtime"),
                            "host": host})
        return out

    def new_ident(self, a, used, dest=None):
        priv, pub, fp = keygen(f"{a['user']}@{a['host']}")
        kh = hashed_known_host([DECOY, dest["ip"]], dest["host_key"]) if dest and dest.get("host_key") else []
        return {"kind": "ssh_key", "value": fp, "private": priv, "public": pub, "known_hosts": kh}

    def ops(self, a, ident, dest):
        h, i = a["home"], a["indent"]
        block = f"Host {DECOY}\n{i}HostName {dest['ip']}\n{i}User backup\n{i}IdentityFile ~/.ssh/{a['keyname']}\n"
        # 키는 옛 백업 서버 시절(2024-06~2025-09)에 만든 것처럼
        made = ts(time.mktime((2024, 7, 2, 10, 14, 33, 0, 0, -1)))
        own = {"owner": a["user"], "group": str(a["gid"])}
        return [
            {"kind": "dir", "path": f"{h}/.ssh", "mode": "0700", **own, "mtime": ts(a["ssh_dir_mtime"]) or made},
            {"kind": "file", "path": f"{h}/.ssh/{a['keyname']}", "content": ident["private"], "mode": "0600", **own, "mtime": made},
            {"kind": "file", "path": f"{h}/.ssh/{a['keyname']}.pub", "content": ident["public"] + "\n", "mode": "0644", **own, "mtime": made},
            {"kind": "block", "path": f"{h}/.ssh/config", "block": block, "mode": "0600", **own, "mtime": ts(a["config_mtime"]) or made},
            # 목적지 쪽: 디코이 backup 계정이 이 키를 받아 준다(로그인 = 경보, 세션 기록)
            {"kind": "decoy_key", "decoy": DECOY, "user": "backup", "line": f"{ident['public']}"},
        ] + [
            # 써 본 서버라면 known_hosts에 있다 — 없으면 첫 접속 때 "처음 보는 호스트" 질문이 떠서 단서(11/22 실측)
            {"kind": "line", "path": f"{h}/.ssh/known_hosts", "regexp": "^" + __import__("re").escape(l) + "$", "line": l,
             "absent_line": None, "mode": "0600", **own, "mtime": ts(a.get("known_hosts_mtime")) or made}
            for l in ident["known_hosts"]
        ]


class History:
    name = "history"
    LINES = [f"ssh {DECOY}", f"ssh {DECOY} 'ls -lh /backup/dumps | tail -3'", f"ssh {DECOY} df -h /backup"]

    def match(self, ctx, host):
        return [{"user": u["name"], "path": u["history"]["path"], "lines": u["history"]["lines"], "mtime": u["history"]["mtime"]}
                for u in shell_users(ctx) if u["name"] != "root" and u["history"] and u["history"]["lines"] >= 20]

    def new_ident(self, a, used):
        return {"kind": "via", "value": "ssh_config"}  # 히스토리는 길잡이(T2로 이끎), 자체 ID 없음

    def ops(self, a, ident, dest):
        # 끝에 붙이면 "최근에 썼다"가 되어 서사(2025-09 이후 방치)와 어긋난다 → 앞쪽 60% 지점에 섞는다
        return [{"kind": "insert", "path": a["path"], "lines": self.LINES + ["exit"], "ratio": 0.6, "boundary": "exit", "mtime": ts(a["mtime"])}]


# ------------------------------------------------------------------ T6형: 남은 AWS 장기 키
class AwsProfile:
    name = "aws_profile"
    PROFILE = "backup-legacy"

    def match(self, ctx, host):
        if not ctx["tools"]["aws"]:
            return []
        return [{"user": u["name"], "home": u["home"], "gid": u["gid"], "cred_mtime": u["aws"]["cred_mtime"]}
                for u in shell_users(ctx)
                # aws를 실제로 쓰는 계정: 그 계정의 cron(또는 cron이 부르는 스크립트)이 aws를 부른다.
                # ~/.aws만 있는 것은 근거가 약하다(로컬 VM root의 CloudWatch 에이전트 자격증명 — 11/22 오판)
                if u["cron_uses_aws"]]  # 이미 backup-legacy가 있으면 내 미끼 자리

    def new_ident(self, a, used):
        # 로컬: 형식만 맞춘 값. AWS(11/28): IAM 사용자 backup-legacy의 실제 액세스 키(권한 없음)로 교체
        kid = "AKIA" + "".join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567") for _ in range(16))
        return {"kind": "aws_key", "value": kid, "secret": secrets.token_urlsafe(30)[:40], "placeholder": True}

    def ops(self, a, ident, dest):
        sec = f"[{self.PROFILE}]\naws_access_key_id = {ident['value']}\naws_secret_access_key = {ident['secret']}\n"
        made = ts(time.mktime((2024, 6, 12, 15, 2, 11, 0, 0, -1)))
        return [{"kind": "dir", "path": f"{a['home']}/.aws", "mode": "0755", "owner": a["user"], "group": str(a["gid"]), "mtime": made},
                {"kind": "block", "path": f"{a['home']}/.aws/credentials", "block": sec, "mode": "0600", "owner": a["user"],
                 "group": str(a["gid"]), "mtime": ts(a["cred_mtime"]) or made}]


# ------------------------------------------------------------------ T4형: 잊힌 tmux 세션의 ssh-agent(메모리에만 있는 키)
class AgentSession:
    name = "agent_session"

    def match(self, ctx, host):
        if not ctx["tools"].get("tmux") or not ctx["tools"].get("ssh-agent"):
            return []
        # 사람이 일하던 계정(히스토리)이고 나가는 ssh를 쓰는 계정 — SSH 미끼와 같은 맥락
        return [{"user": u["name"], "host": host} for u in shell_users(ctx)
                if u["name"] != "root" and u["history"] and u["history"]["lines"] >= 20
                and (u["known_hosts"] or u["keys"] or u["ssh_config"])]

    def new_ident(self, a, used, dest=None):
        priv, pub, fp = keygen(f"{a['user']}@{a['host']}")
        return {"kind": "ssh_key", "value": fp, "private": priv, "public": pub}

    def ops(self, a, ident, dest):
        return [{"kind": "agent_session", "user": a["user"], "session": "0", "fingerprint": ident["value"], "private": ident["private"],
                 "reboot_ok": True},
                {"kind": "decoy_key", "decoy": DECOY, "user": "backup", "line": ident["public"]}]


# ------------------------------------------------------------------ T5형: 꺼진 기능의 멈춘 동기화 서비스(환경변수)
class SyncService:
    name = "sync_service"
    POOL = ["sync_svc", "report_sync", "rpt_sync"]
    # 꺼진 상태에서도 사본 DB 쪽 연결을 하나 잡아 둔다(핸드셰이크만, 데이터 없음) → 침투한 공격자의 netstat·ss·ip neigh에
    # 디코이가 보인다(Attivo US10375110 "연결 테이블 미끼"). 무작위 간격으로 끊고 다시 맺는다. 디코이 쪽 관문은 페이로드 없는 연결을 알리지 않는다
    SCRIPT = """#!/usr/bin/env python3
# {feature} 사본 동기화 (2024-07). {flag}=false 이면 동기화는 쉬고 연결만 유지한다.
import logging, os, random, socket, time
from urllib.parse import urlsplit
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("{name}")
u = urlsplit(os.environ.get("SYNC_DB_URL", ""))
while True:
    if os.environ.get("{flag}", "false").lower() == "true":
        log.info("sync start")
        time.sleep(int(os.environ.get("SYNC_INTERVAL", "86400")))
        continue
    try:
        s = socket.create_connection((u.hostname, u.port or 5432), timeout=10)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        s.settimeout(60)
        until = time.time() + random.randint(1800, 7200)
        while time.time() < until:  # 1분마다 살아 있는지 — 끊기면 곧 다시 잡는다
            try:
                if not s.recv(1):
                    break
            except socket.timeout:
                continue
        s.close()
    except OSError:
        time.sleep(60)
"""

    # Attivo 연결 테이블을 끈 상태: 꺼진 기능답게 쉬기만 한다(연결 없음)
    IDLE = """#!/usr/bin/env python3
# {feature} 사본 동기화 (2024-07). {flag}=false 이면 동기화는 쉰다.
import logging, os, time
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("{name}")
while True:
    if os.environ.get("{flag}", "false").lower() == "true":
        log.info("sync start")
    time.sleep(int(os.environ.get("SYNC_INTERVAL", "86400")))
"""

    def match(self, ctx, host):
        out = []
        for svc in ctx["services"]:
            for ef in svc["env_files"]:
                keys = {k["key"]: k for k in ef["keys"]}
                for k in ef["keys"]:
                    m = re.match(r"^([A-Z]+)_ENABLED$", k["key"])
                    if m and f"{m.group(1)}_DB_URL" in keys:  # 꺼진 기능 플래그 + 그 기능의 DB 주소 = 그 기능용 작업이 있었을 법함
                        p = m.group(1).lower()
                        main = keys.get("DATABASE_URL", {})
                        out.append({"prefix": m.group(1), "name": f"{p}-sync", "flag": k["key"], "env_file": ef["path"],
                                    "user": svc["user"] or "root", "scheme": main.get("scheme", "postgresql"),
                                    "db": main.get("db") or "postgres", "host": host})
        return out

    def new_ident(self, a, used, dest=None):
        n = next((x for x in self.POOL if x not in used), f"sync_{secrets.token_hex(2)}")
        return {"kind": "db_user", "value": n, "password": pw()}

    def ops(self, a, ident, dest, crumbs=True, conn=True):
        """crumbs = Illusive 맥락 미끼(T5: 환경변수의 미끼 DB 계정), conn = Attivo 연결 테이블(핸드셰이크만 한 연결). 벤더 기술 스위치(11/23)
        둘 다 끄면 서비스 자체가 없음(엔진이 회수), crumbs만 끄면 계정 없는 URL로 연결만, conn만 끄면 연결 없이 대기"""
        made = ts(time.mktime((2024, 7, 8, 16, 20, 5, 0, 0, -1)))
        cred = f"{ident['value']}:{ident['password']}@" if crumbs else ""
        url = f"{a['scheme']}://{cred}{DECOY}:5432/{a['db']}"
        unit = (f"[Unit]\nDescription={a['prefix'].lower()} copy sync\nAfter=network-online.target\n\n[Service]\nUser={a['user']}\n"
                f"EnvironmentFile={a['env_file']}\nEnvironment=SYNC_DB_URL={url}\nEnvironment=SYNC_INTERVAL=86400\n"
                f"ExecStart=/usr/bin/python3 /usr/local/bin/{a['name']}\nRestart=on-failure\n\n[Install]\nWantedBy=multi-user.target\n")
        script = (self.SCRIPT if conn else self.IDLE).format(feature=a["prefix"].lower(), flag=a["flag"], name=a["name"])
        return [{"kind": "file", "path": f"/usr/local/bin/{a['name']}", "content": script, "mode": "0755", "owner": "root", "group": "root", "mtime": made},
                {"kind": "file", "path": f"/etc/systemd/system/{a['name']}.service", "content": unit, "mode": "0644", "owner": "root", "group": "root", "mtime": made},
                {"kind": "unit", "name": f"{a['name']}.service", "mtime": made,
                 "files": [f"/usr/local/bin/{a['name']}", f"/etc/systemd/system/{a['name']}.service"]}]


# ------------------------------------------------------------------ 디코이 포트: 운영 서버(EDH)의 안 쓰는 포트 → farm 트랩(US10404747)
class DecoyPort:
    name = "decoy_port"
    # 역할 → 그 서버에 있을 법한 서비스(진짜 소프트웨어로 트랩). 이미 쓰는 포트는 학습 단계에서 뺀다
    ROLE = [("postgres", "redis", 6379), ("nginx", "nginx-auth", 8080)]

    def match(self, ctx, host, conf=None):
        import ipaddress
        lan = ipaddress.ip_network((conf or {}).get("lan_cidr", "10.0.0.0/16"))
        ifc = next((i for i in ctx.get("net", {}).get("ifaces", []) if ipaddress.ip_interface(i["addr"]).ip in lan), None)
        if not ifc:
            return []
        out = []
        for proc, svc, port in self.ROLE:
            if proc in ctx["processes"] and port not in ctx.get("listening", []):
                net = ipaddress.ip_interface(ifc["addr"]).network
                out.append({"host": host, "service": svc, "port": port, "iface": ifc["iface"], "addr": ifc["addr"],
                            "gw": str(net.network_address + 1)})
        return out

    def new_ident(self, a, used, dest=None):
        return {"kind": "decoy_port", "value": f"{a['host']}:{a['port']}"}

    def ops(self, a, ident, dest):
        return []  # 여러 단계(키 교환)라 엔진의 place_decoy_port가 한다


# ------------------------------------------------------------------ 디코이 포트를 가리키는 미끼(특허: 활성 디코이 포트를 가리키는 것만 배치)
class CacheHint:
    name = "cache_hint"

    def match(self, ctx, host):
        out = []
        live = {(d["host"], d["service"], d["port"]) for d in ctx.get("_decoy_ports", [])}
        for svc in ctx["services"]:
            for ef in svc["env_files"]:
                keys = {k["key"]: k for k in ef["keys"]}
                main = keys.get("DATABASE_URL", {})
                dbh = main.get("host")
                hit = next(((h, p) for h, sv, p in live if h == dbh and sv == "redis"), None)
                if hit and "CACHE_URL" not in keys:  # 앱이 쓰는 DB 서버에 Redis 디코이 포트가 있을 때만
                    out.append({"path": ef["path"], "edh": hit[0], "port": hit[1], "file_mtime": ef["mtime"]})
        return out

    def new_ident(self, a, used, dest=None):
        return {"kind": "via", "value": f"{a['edh']}:{a['port']}"}  # 목적지 디코이 포트가 곧 ID(EDH 경보가 잡음)

    def ops(self, a, ident, dest):
        # 앱 코드엔 없는 변수라 살아 있는 설정이면 git grep에서 어색하다 → 보류된 설정이 주석으로 남은 모양
        blk = f"# 세션 저장소를 Redis로 옮기려다 보류 (2024-10)\n# CACHE_URL=redis://{a['edh']}:{a['port']}/0\n"
        return [{"kind": "block", "path": a["path"], "block": blk, "mtime": ts(a["file_mtime"])}]


# ------------------------------------------------------------------ 투영 디코이(Acalvio 투영): 자리는 서버 하나가 아니라 구간 — blend.py가 정하고 엔진이 배치
class Projection:
    name = "projection"

    def match(self, ctx, host):
        return []  # 서버별 규칙이 아님(engine.plan_projection)

    def new_ident(self, a, used):
        return {"kind": "projection", "value": f"{a['name']}@{a['addr'].split('/')[0]}"}

    def ops(self, a, ident, dest):
        return []  # 여러 단계(센서 → 팜 VM)라 엔진의 place_projection이 한다


TYPES = {t.name: t for t in (EnvDbUrl(), SshConfig(), History(), AwsProfile(), AgentSession(), SyncService(), DecoyPort(), CacheHint(),
                             Projection())}
