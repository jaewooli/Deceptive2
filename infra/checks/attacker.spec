# 공격자 시점(infra/checks/paths.py) — 환경 중립. 기대값을 박지 않고 "디코이 = 진짜 서버"를 그 자리에서 비교한다(same)
# 기준 서버: app-01(진짜 회사 서버). 다른 구간끼리도 VPC는 TTL을 안 줄이므로 비교가 성립(로컬은 router가 보정 — lab.spec)
# tcpdump 출력은 표준출력으로(서버에 파일 남기지 않음). 명령 안에 ' | ' 금지(구분자)

# ---- L3: 중계된 디코이도 진짜 서버와 같게 — 11/23 실측 단서(TTL 62, MSS 1340, DF 소실, traceroute 무응답)
web-01 | same | ping -c1 -W2 {T} | ttl=(\d+) @ {proj:stg:ip} ~ {ip:app-01} | stg ICMP TTL = app-01
web-01 | same | ping -c1 -W2 -M do -s $(( $(cat /sys/class/net/{if:web-01}/mtu) - 28 )) {T} | (\d+) bytes from @ {proj:stg:ip} ~ {ip:app-01} | stg: 구간 MTU 크기 DF 통과 = app-01(PMTU 블랙홀 없음)
web-01 | same | tracepath -n -m 4 {T} | ^ (\d+):\s+\S+\s.*reached @ {proj:stg:ip} ~ {ip:app-01} | stg traceroute 홉 수 = app-01
web-01 | same | timeout 5 tcpdump -c1 -nvi {if:web-01} "src host {T} and src port 22 and tcp[13]&18==18" 2>/dev/null & sleep 1; timeout 2 bash -c "exec 3<>/dev/tcp/{T}/22"; wait | (ttl \d+)[\s\S]*?(mss \d+) @ {proj:stg:ip} ~ {ip:app-01} | stg SYN-ACK TTL·MSS = app-01
web-01 | same | timeout 3 bash -c "exec 3<>/dev/tcp/{T}/22; read -r l <&3; echo \$l" | (SSH-[^\r\n]+) @ {proj:stg:ip} ~ {ip:app-01} | stg SSH 배너 = app-01(같은 패치 수준)
web-01 | has | ping -c1 -W2 {proj:stg:ip} >/dev/null; ip neigh show {proj:stg:ip} | lladdr {proj:stg:mac} | stg ARP 값 = 디코이 NIC MAC(센서 투영 NIC)
app-01 | same | ping -c1 -W2 {T} | ttl=(\d+) @ {proj:dev:ip} ~ {ip:db-backup-01} | dev ICMP TTL = 같은 구간 서버
app-01 | same | timeout 5 tcpdump -c1 -nvi {if:app-01} "src host {T} and src port 22 and tcp[13]&18==18" 2>/dev/null & sleep 1; timeout 2 bash -c "exec 3<>/dev/tcp/{T}/22"; wait | (ttl \d+)[\s\S]*?(mss \d+) @ {proj:dev:ip} ~ {ip:db-backup-01} | dev SYN-ACK TTL·MSS = 같은 구간 서버
app-01 | same | timeout 3 bash -c "exec 3<>/dev/tcp/{T}/22; read -r l <&3; echo \$l" | (SSH-[^\r\n]+) @ {proj:dev:ip} ~ {ip:db-backup-01} | dev SSH 배너 = 같은 구간 서버

# ---- 트랩 중계: 넘긴 포트도 같은 서버의 다른 포트와 같게
web-01 | same | timeout 5 tcpdump -c1 -nvi {if:web-01} "src host {ip:app-01} and src port {T} and tcp[13]&18==18" 2>/dev/null & sleep 1; timeout 2 bash -c "exec 3<>/dev/tcp/{ip:app-01}/{T}"; wait | (ttl \d+)[\s\S]*?(mss \d+) @ {trap:app-01:port} ~ 22 | 트랩 app-01 넘긴 포트 SYN-ACK = app-01:22
app-01 | same | timeout 5 tcpdump -c1 -nvi {if:app-01} "src host {ip:web-01} and src port {T} and tcp[13]&18==18" 2>/dev/null & sleep 1; timeout 2 bash -c "exec 3<>/dev/tcp/{ip:web-01}/{T}"; wait | (ttl \d+)[\s\S]*?(mss \d+) @ {trap:web-01:port} ~ 22 | 트랩 web-01 넘긴 포트 SYN-ACK = web-01:22

# ---- 응용 계층
web-01 | has | timeout 15 ssh -n -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {proj:stg:ip} true 2>&1 | Permission denied \(publickey\) | stg SSH 키 교환 끝까지(인증 단계 도달)
web-01 | has | timeout 5 curl -s -o /dev/null -w '%{http_code}' http://{proj:stg:ip}/ | ^200$ | stg 웹(옛 스테이징 앱) 응답
web-01 | has | timeout 3 bash -c 'exec 3<>/dev/tcp/{ip:app-01}/{trap:app-01:port}; printf "CLIENT LIST\r\nQUIT\r\n" >&3; cat <&3' | addr={ip:web-01}:\d+ laddr={ip:app-01}:{trap:app-01:port} | 트랩 Redis CLIENT LIST: 진짜 출발지·EDH 주소
