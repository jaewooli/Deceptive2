#!/usr/bin/env bash
# E3: 디코이의 주소마다 스캐너가 보는 것(배너·KEX·호스트 키 지문·열린 포트) — 로그인하지 않는다
#   validation/probe_addrs.sh "<이름> <주소> <ssh포트> <pg포트>" ...
#   로컬 VM: validation/probe_addrs.sh "주 127.0.0.1 2231 15431" "보조1 127.0.0.1 2241 15441" ...
# 같은 호스트 키를 내는 주소가 있으면 스캐너는 그 주소들을 "한 대"로 묶는다
set -uo pipefail
echo "### E3"
for spec in "$@"; do
  read -r name host sp pp <<<"$spec"
  banner=$(timeout 5 bash -c "exec 3<>/dev/tcp/$host/$sp; head -n 1 <&3" 2>/dev/null | tr -d '\r')
  kex=$(ssh -vvv -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o PreferredAuthentications=none -o ConnectTimeout=5 -p "$sp" nobody_check@"$host" true 2>&1 |
        awk '/peer server KEXINIT proposal/{p=1;next} /first_kex_follows/{p=0} p' | md5sum | cut -c1-12)
  fps=$(ssh-keyscan -T 5 -p "$sp" "$host" 2>/dev/null | ssh-keygen -lf - 2>/dev/null | awk '{print $2}' | sort | tr '\n' ' ')
  # 연결만으로는 "열림"으로 치지 않는다(로컬 QEMU 포워딩은 게스트 포트가 닫혀도 연결을 받아 줌) → SSLRequest 응답까지
  pg=$(python3 -I -c 'import socket,struct,sys
try:
    s=socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=3); s.sendall(struct.pack("!II",8,80877103)); r=s.recv(1)
    print("open" if r in (b"S",b"N") else "closed")
except Exception: print("closed")' "$host" "$pp")
  echo "addr name=$name ssh=${banner:-none} kex=$kex pg=$pg keys=$fps"
done
