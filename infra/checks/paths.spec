# 경로 단언(infra/checks/paths.py) — 환경 중립(로컬·AWS 같은 명세). 주소·NIC는 자리표시자, 환경 값은 infra/env/<환경>.yml
# 구분자 ' | '. 아직 배치 안 된 디코이를 가리키는 줄은 "건너뜀"

# ---- 모든 중계 홉: local 규칙(pref 0)이 살아 있어야 서버가 자기 주소로 오는 패킷을 받는다(11/22 먹통 원인)
{sensor} | has | ip rule show pref 0 | lookup local | 센서: local 규칙 pref 0
{farm} | has | ip rule show pref 0 | lookup local | 팜: local 규칙 pref 0
app-01 | has | ip rule show pref 0 | lookup local | app-01: local 규칙 pref 0
web-01 | has | ip rule show pref 0 | lookup local | web-01: local 규칙 pref 0
# 팜의 기본 경로·main/default 규칙은 팜 장치가 건드리지 않는다(WSL2 팜 = 사용자 작업 환경, docs/local-farm-recovery.md)
{farm} | has | ip rule show | ^32766:\s+from all lookup main | 팜: main 규칙 그대로
{farm} | hasnt | ip rule show | ^([1-9]|[1-4][0-9]):\s | 팜: pref 1~48에 낯선 규칙 없음(팜 규칙은 49~)
# networkd가 외래 규칙·경로를 지우지 않게(networkd를 쓰는 서버만 — WSL2 팜은 networkd 없음)
{sensor} | has | cat /etc/systemd/networkd.conf.d/10-keep-foreign.conf | ManageForeignRoutingPolicyRules=no | 센서: networkd 외래 규칙 보존
app-01 | has | cat /etc/systemd/networkd.conf.d/10-keep-foreign.conf | ManageForeignRoutingPolicyRules=no | app-01: networkd 외래 규칙 보존
web-01 | has | cat /etc/systemd/networkd.conf.d/10-keep-foreign.conf | ManageForeignRoutingPolicyRules=no | web-01: networkd 외래 규칙 보존

# ---- 투영(Acalvio): 공격자 → 센서(구간 NIC) → relay → 팜 → 디코이 VM(탭 ve-<이름>), 응답은 같은 터널로 거꾸로
{sensor} | route | {proj:stg:ip} from {ip:web-01} iif {proj:stg:nic} | relay | 센서: stg 주소로 온 것 → 터널
{sensor} | route | {ip:web-01} from {proj:stg:ip} iif relay | {proj:stg:nic} | 센서: stg 응답 → 그 구간 NIC
{sensor} | route | {ip:app-01} from {proj:stg:ip} iif relay | {proj:stg:nic} | 센서: stg 응답(다른 구간) → 그 구간 NIC(게이트웨이)
{sensor} | route | {proj:dev:ip} from {ip:app-01} iif {proj:dev:nic} | relay | 센서: dev 주소로 온 것 → 터널
{sensor} | route | {ip:app-01} from {proj:dev:ip} iif relay | {proj:dev:nic} | 센서: dev 응답 → 그 구간 NIC
{sensor} | has | iptables -t mangle -S PREROUTING | -i relay -j TTL --ttl-inc 1 | 센서: 팜 응답 TTL 보정
{sensor} | has | iptables -t mangle -S PREROUTING | -d {proj:stg:ip}/32 -i {proj:stg:nic} -j TTL --ttl-inc 1 | 센서: stg로 들어온 것 TTL 보정
{sensor} | hasnt | ip -4 -o addr show | inet {proj:stg:ip}/ | 센서: 투영 주소를 자기 주소로 두지 않음(fail-safe)
{sensor} | hasnt | iptables -t mangle -S | TCPMSS | 센서: MSS 조정 없음(11/23 — 조정 자체가 단서)
{farm} | route | {proj:stg:ip} from {ip:web-01} iif relay | ve-{proj:stg:name} | 팜: 터널로 온 것 → stg VM
{farm} | route | {ip:web-01} from {proj:stg:ip} iif ve-{proj:stg:name} | relay | 팜: stg 응답 → 터널(비면 LAN 직행 — 11/23 키 교환 멈춤)
{farm} | route | {proj:dev:ip} from {ip:app-01} iif relay | ve-{proj:dev:name} | 팜: 터널로 온 것 → dev VM
{farm} | route | {ip:app-01} from {proj:dev:ip} iif ve-{proj:dev:name} | relay | 팜: dev 응답 → 터널
{farm} | has | ip route show table 120 | unreachable default .*metric 4000 | 팜: 터널이 없으면 디코이 응답을 버림(fail-closed)
{farm} | has | ip route show {proj:stg:ip}/32 | blackhole .*metric 1000 | 팜: stg가 죽어도 응답이 새지 않음
{farm} | has | sysctl -n net.ipv4.conf.all.arp_ignore | ^1$ | 팜: 다른 NIC 주소로 ARP에 답하지 않음(라우터 .1 가로채기 — 11/23)
{farm} | hasnt | ip -4 -o addr show | inet {proj:stg:gw}/ | 팜: 디코이 게이트웨이(.1)를 자기 주소로 두지 않음
{farm} | has | iptables -t mangle -S PREROUTING | -i relay -j TTL --ttl-inc 1 | 팜: 터널로 온 것 TTL 보정
{farm} | has | iptables -t mangle -S PREROUTING | -i ve-\+ -j TTL --ttl-inc 1 | 팜: 디코이 응답 TTL 보정
{farm} | hasnt | iptables -t mangle -S | TCPMSS | 팜: MSS 조정 없음
{farm} | has | systemctl is-active guest@{proj:stg:name} | ^active$ | 팜: stg VM 동작
{farm} | has | systemctl is-active guest@{proj:dev:name} | ^active$ | 팜: dev VM 동작
# 터널 MTU = 구간 MTU(이웃 서버의 NIC MTU와 같아야 — 11/23 MSS·PMTU 단서)
web-01 | same | cat /sys/class/net/{T}/mtu | ^(\d+)$ @ {if:web-01} ~ wg0 | web-01: 트랩 터널 MTU = LAN NIC MTU

# ---- 트랩 중계(Illusive): 공격자 → EDH 빈 포트 → (DNAT 169.254.200.1) wg0 → 팜 edhN → 트랩(EDH 주소), 응답은 같은 터널
app-01 | route | 169.254.200.1 | wg0 | app-01(EDH): 트랩 중계 주소 → wg0
app-01 | has | nft list table ip local_fwd | daddr {ip:app-01} tcp dport {trap:app-01:port} .*dnat to 169\.254\.200\.1 | app-01: 넘길 포트 → 중계 주소
app-01 | has | iptables -t mangle -S LOCAL_FWD | -i wg0 -j TTL --ttl-inc 1 | app-01: 트랩 응답 TTL 보정(moa-notify)
web-01 | route | 169.254.200.1 | wg0 | web-01(EDH): 트랩 중계 주소 → wg0
web-01 | has | nft list table ip local_fwd | daddr {ip:web-01} tcp dport {trap:web-01:port} .*dnat to 169\.254\.200\.1 | web-01: 넘길 포트 → 중계 주소
web-01 | has | iptables -t mangle -S LOCAL_FWD | -i wg0 -j TTL --ttl-inc 1 | web-01: 트랩 응답 TTL 보정(moa-notify)
{farm} | route | {ip:app-01} from {ip:web-01} iif {trap:app-01:tun} | ve-trap-app-01 | 팜: app-01 트랩 터널 → 트랩
{farm} | route | {ip:web-01} from {ip:app-01} iif ve-trap-app-01 | {trap:app-01:tun} | 팜: app-01 트랩 응답 → 같은 터널
{farm} | route | {ip:web-01} from {ip:app-01} iif {trap:web-01:tun} | ve-trap-web-01 | 팜: web-01 트랩 터널 → 트랩
{farm} | route | {ip:app-01} from {ip:web-01} iif ve-trap-web-01 | {trap:web-01:tun} | 팜: web-01 트랩 응답 → 같은 터널
{farm} | has | iptables -t mangle -S PREROUTING | -i {trap:app-01:tun} -j TTL --ttl-inc 1 | 팜: app-01 트랩 터널 TTL 보정
