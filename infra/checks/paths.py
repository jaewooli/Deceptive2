#!/usr/bin/env python3
"""경로 단언 — 설계한 중계 경로가 각 홉의 커널 경로표에서 실제로 그 장치로 가는지 확인한다(트래픽 없이 몇 초).

왜(11/22~23 장애): 경로표가 비면 패킷은 조용히 다른 길로 간다(투영 응답이 터널을 우회 → SSH 키 교환 멈춤),
local 규칙이 지워지면 서버 전체가 먹통이 된다. 둘 다 배포·재부팅 뒤 "상태"의 문제라 정적 검사로는 못 잡는다.

  python3 infra/checks/paths.py infra/checks/paths.local.txt            # 로컬 랩(lab.sh ssh)
  python3 infra/checks/paths.py SPEC --transport '<명령 {host}>'          # 다른 전송(예: AWS SSM 래퍼). 표준입력의 셸 스크립트를 root로 실행해야 함

명세 한 줄: 호스트 | 종류 | 인자 | 기대 | 설명
  route : 인자 = `ip route get`의 인자(<목적지> [from <출발지>] [iif <장치>]), 기대 = 나가는 장치(dev) 또는 blackhole/unreachable
  has   : 인자 = 셸 명령, 기대 = 출력에 있어야 하는 정규식
  hasnt : 인자 = 셸 명령, 기대 = 출력에 없어야 하는 정규식
서버에는 아무 파일도 남기지 않는다(스크립트는 표준입력으로).
"""
import argparse
import re
import shlex
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRANSPORT = f"{ROOT}/infra/local-vm/lab.sh ssh {{host}} 'sudo sh -s'"


def load(spec):
    checks = []
    for n, line in enumerate(Path(spec).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 5 or parts[1] not in ("route", "has", "hasnt"):
            sys.exit(f"{spec}:{n}: 형식 오류: {line}")
        checks.append(dict(zip(("host", "kind", "arg", "want", "why"), parts), line=n))
    return checks


def script_for(checks):
    out = ["exec 2>&1"]
    for i, c in enumerate(checks):
        out.append(f"echo; echo @@{i}")   # 앞 명령 출력이 줄바꿈 없이 끝나도(curl -w) 구분 표시가 붙지 않게
        out.append(f"ip -o route get {c['arg']}" if c["kind"] == "route" else f"( {c['arg']} ) || true")
    out.append("echo; echo @@end")
    return "\n".join(out) + "\n"


def judge(c, text):
    if c["kind"] == "route":
        m = re.search(r"\bdev (\S+)", text)
        got = m.group(1) if m else (text.split()[0] if text.split() else "(없음)")
        if not m:
            for word in ("blackhole", "unreachable", "prohibit"):
                if word in text:
                    got = word
        return got == c["want"], got
    found = re.search(c["want"], text, re.M) is not None
    ok = found if c["kind"] == "has" else not found
    return ok, (text.strip().splitlines() or ["(출력 없음)"])[0][:80]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--transport", default=DEFAULT_TRANSPORT)
    ap.add_argument("--host", action="append", help="이 호스트만(여러 번)")
    a = ap.parse_args()

    by_host = OrderedDict()
    for c in load(a.spec):
        if not a.host or c["host"] in a.host:
            by_host.setdefault(c["host"], []).append(c)

    fails = 0
    for host, checks in by_host.items():
        cmd = a.transport.format(host=shlex.quote(host))
        try:
            r = subprocess.run(cmd, shell=True, input=script_for(checks), capture_output=True, text=True, timeout=60)
            raw = r.stdout
        except subprocess.TimeoutExpired:
            raw = ""
        blocks = re.split(r"^@@(\d+|end)$", raw, flags=re.M)
        res = {int(blocks[k]): blocks[k + 1] for k in range(1, len(blocks) - 1, 2) if blocks[k].isdigit()}
        if "@@end" not in raw:
            print(f"✗ {host}: 접속·실행 실패 — 이 호스트의 단언 {len(checks)}개 판정 불가")
            fails += len(checks)
            continue
        for i, c in enumerate(checks):
            ok, got = judge(c, res.get(i, ""))
            fails += not ok
            mark = "✓" if ok else "✗"
            detail = "" if ok else f"  (기대 {c['want']!r}, 실제 {got!r})"
            print(f"{mark} {host:<8} {c['kind']:<5} {c['why']}{detail}")
    print(f"\n{'통과' if not fails else f'실패 {fails}개'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
