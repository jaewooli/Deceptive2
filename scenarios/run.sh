#!/usr/bin/env bash
# 시나리오 리허설 러너 — 상관기(출발지 포렌식)를 켜고 시나리오를 돌린 뒤, 어떤 경보가 왔는지·체인이 묶였는지 판정한다.
#   scenarios/run.sh <1|2|3>
# 보는 것: 수신기(webhook.jsonl)의 이번 구간 경보를 source별로 세고, 시나리오가 기대하는 탐지가 다 왔는지(○/✗),
#          그다음 forensics/chain.py build 로 침투 체인이 한 공격자로 묶였는지.
# 성공 기준(plan-wbs 5절): P0 탐지 단계 경보 100%, 호스트 경보 60초 이내(detect.py 가 시간은 따로 잼), 시나리오1 체인+포렌식.
set -euo pipefail
N="${1:?사용법: scenarios/run.sh <1|2|3>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CTL="${CTL_PY:-$HOME/.cache/deceptive2-ctl/bin/python}"
SINK="$HOME/.cache/deceptive2-vm/webhook.jsonl"
OUT="$ROOT/out/scenarios"; mkdir -p "$OUT"
SC="$ROOT/scenarios/scenario${N}.sh"
[ -x "$SC" ] || chmod +x "$SC"
[ -f "$SC" ] || { echo "없음: $SC"; exit 1; }

# 시나리오별 기대 탐지(경보 source)
case "$N" in
  1) EXPECT="감사 포트 sshd 세션 postgresql 터널 포렌식 체인" ;;
  2) EXPECT="감사" ;;
  3) EXPECT="sshd 세션 감사" ;;
  *) echo "시나리오 번호는 1·2·3"; exit 1 ;;
esac

n0=$(wc -l < "$SINK" 2>/dev/null || echo 0)

# 출발지 포렌식 상관기 — forensics 스위치가 켜져 있으면 띄운다(짧은 연결의 P를 잡으려면 접속 중에 돌아야 함)
COR=""
if "$CTL" "$ROOT/baits/engine.py" feature - status 2>/dev/null | grep -q '^forensics  *on'; then
  "$CTL" "$ROOT/forensics/correlate.py" watch >"$OUT/correlate.$N.log" 2>&1 &
  COR=$!
  echo "[run] 출발지 포렌식 상관기 켬 (pid $COR)"
  sleep 1
fi
cleanup(){ [ -n "$COR" ] && kill "$COR" 2>/dev/null || true; }
trap cleanup EXIT

echo "[run] 시나리오 $N 실행"
"$SC" 2>&1 | sed 's/^/  /'

echo "[run] 비동기 경보 대기(engagement·포렌식·체인) …"
sleep 18
cleanup; COR=""

n1=$(wc -l < "$SINK")
last=$(( n1 - n0 + 5 ))
echo
echo "========== 판정: 시나리오 $N (수신기 구간 ${n0}→${n1}, +$((n1-n0))줄) =========="
EXPECT="$EXPECT" START="$n0" SINK="$SINK" "$CTL" - <<'PY'
import json, os
sink=os.environ["SINK"]; start=int(os.environ["START"]); expect=os.environ["EXPECT"].split()
rows=[]
for i,ln in enumerate(open(sink,encoding="utf-8"),1):
    if i<=start: continue
    try: b=json.loads(ln)["body"]
    except: continue
    rows.append(b)
# source별 집계
from collections import Counter, defaultdict
cnt=Counter(r.get("source") for r in rows)
print("경보 source별:")
for s,c in cnt.most_common():
    print(f"   {c:4}  {s}")
# 관리 세션 소음(auid=ubuntu/ssm) 구별: 감사 중 client가 amazon-ssm 등은 기준선 소음
noise=sum(1 for r in rows if r.get("source")=="감사" and str(r.get("client","")).startswith("amazon-ssm"))
if noise: print(f"   (그중 감사 {noise}건은 SSM/CloudWatch 관리 소음 — 기준선 오탐 재료)")
print()
print("기대 탐지:")
ok=True
for e in expect:
    got=cnt.get(e,0)
    print(f"   {'○' if got else '✗'}  {e:12} {got}건")
    if not got: ok=False
# 미끼→털린 위치(체인에 실린 값)
chains=[r for r in rows if r.get("source")=="체인"]
if chains:
    print("\n체인 경보:")
    for r in chains[-3:]:
        print("  ", (r.get("result") or "")[:160])
print("\n결과:", "○ 기대 탐지 모두 도착" if ok else "✗ 빠진 탐지 있음(위 ✗)")
PY

echo
echo "[run] 침투 체인 재구성 (forensics/chain.py build):"
"$CTL" "$ROOT/forensics/chain.py" build --last "$last" 2>&1 | sed 's/^/  /' || true
echo "[run] 끝 — 원자료: $SINK, out/chains/, out/forensics/, out/scenarios/"
