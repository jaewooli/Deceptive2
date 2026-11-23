#!/usr/bin/env python3
"""탐지 검사 — 공격자 자리에서 탐지 경로마다 실제로 건드리고, 경보가 수신기에 도착하기까지의 시간을 잰다(성공 기준: 호스트 경보 60초 이내).
  python3 infra/checks/detect.py
- 수신기 = 환경 프로필 notify(로컬: infra/local-vm/webhook_sink.py → ~/.cache/deceptive2-vm/webhook.jsonl)
- 꺼진 벤더 기술(engine.py feature)의 경로는 건너뜀. 주소는 렌더된 destinations·레지스트리·맥락에서(paths.py와 같은 자리표시자)
- 건드리는 것 자체가 디코이 쪽 기록을 남긴다(측정 흔적 — 공격자 행동과 같은 모양)
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths  # noqa: E402

SINK = Path(os.path.expanduser("~/.cache/deceptive2-vm/webhook.jsonl"))
LIMIT = 60

# (이름, 필요한 기술(None=항상), 건드릴 호스트, 명령, 경보에서 찾을 것 {필드: 포함할 문자열})
CASES = [
    ("디코이 DB(PG) 접속", None, "web-01",
     "timeout 3 bash -c 'exec 3<>/dev/tcp/{ip:db-backup-01}/5432; printf \"\\000\\000\\000\\010\\004\\322\\026\\057\" >&3; head -c1 <&3'",
     {"source": "postgresql", "client": "{ip:web-01}"}),
    ("디코이 SSH(T2 미끼 키)", "breadcrumbs", "web-01",
     "sudo -u deploy -H ssh -o BatchMode=yes -o ConnectTimeout=5 db-backup-01 true",
     {"source": "sshd", "client": "{ip:web-01}", "result": "SHA256:"}),
    ("투영 stg-01", "projection", "web-01", "timeout 3 bash -c 'exec 3<>/dev/tcp/{proj:stg:ip}/22; read -r l <&3'",
     {"source": "투영", "result": "{proj:stg:name}("}),
    ("투영 dev-01", "projection", "app-01", "timeout 3 bash -c 'exec 3<>/dev/tcp/{proj:dev:ip}/22; read -r l <&3'",
     {"source": "투영", "result": "{proj:dev:name}("}),
    ("트랩 app-01 빈 포트", "trap", "web-01", "timeout 3 bash -c 'exec 3<>/dev/tcp/{ip:app-01}/{trap:app-01:port}; printf \"PING\\r\\n\" >&3; head -c5 <&3'",
     {"source": "포트", "client": "{ip:web-01}"}),
]


def sink_lines():
    try:
        return SINK.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def main():
    v, dest = paths.variables()
    paths.VARS = v
    fails = 0
    for name, feat, host, cmd, want in CASES:
        if feat and f"feat:{feat}" not in v:
            print(f"· 건너뜀 {name}  ({feat} 꺼짐)")
            continue
        try:
            cmd_f = paths.fill(cmd, v)
            want_f = {k: paths.fill(x, v) for k, x in want.items()}
        except paths.Missing as e:
            print(f"· 건너뜀 {name}  ({{{e}}} 없음)")
            continue
        n0 = len(sink_lines())
        t0 = time.time()
        # 다른 검사와 같은 접속(프로필 access): 명령은 표준입력으로 root 셸에
        subprocess.run(paths.transport(host, dest), shell=True, input=cmd_f + "\n", capture_output=True, text=True, timeout=60)
        got = None
        while time.time() - t0 < LIMIT and not got:
            for line in sink_lines()[n0:]:
                b = json.loads(line).get("body", {})
                if all(x in str(b.get(k, "")) for k, x in want_f.items()):
                    got = (time.time() - t0, b)
                    break
            time.sleep(0.3)
        if got:
            b = got[1]
            print(f"✓ {name}: {got[0]:.1f}초 — {b.get('host')} {b.get('source')} {b.get('client')} {str(b.get('result'))[:70]}")
        else:
            fails += 1
            print(f"✗ {name}: {LIMIT}초 안에 경보 없음(찾은 조건 {want_f})")
    print(f"\n{'통과' if not fails else f'실패 {fails}개'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
