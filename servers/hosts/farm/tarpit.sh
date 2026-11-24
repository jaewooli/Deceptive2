#!/usr/bin/env bash
# 연결 수립 지연: <dev>로 나가는 TCP SYN+ACK만 <ms> 늦춘다(다른 패킷은 그대로). relay PostUp·PreDown과 관리 쪽이 부른다
#   tarpit.sh on <dev> <ms> | off <dev>
set -euo pipefail
dev=${2:?dev}
tc qdisc del dev "$dev" root 2>/dev/null || true
[ "$1" = on ] || exit 0
tc qdisc add dev "$dev" root handle 1: prio bands 4 priomap 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1   # 모든 트래픽 = 1:2(지연 없음)
tc qdisc add dev "$dev" parent 1:4 handle 40: netem delay "${3:?ms}ms"
# IPv4 IHL 5(옵션 없음), TCP, 플래그가 정확히 SYN+ACK(20+13바이트째) → 1:4. u32의 nexthdr+는 해시 설정 없이는 0이라 안 맞았음(11/24)
tc filter add dev "$dev" parent 1: protocol ip prio 1 u32 match u8 0x05 0x0f at 0 match ip protocol 6 0xff match u8 0x12 0xff at 33 flowid 1:4
