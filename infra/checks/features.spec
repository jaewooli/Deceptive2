# 벤더 기술 스위치 검사(infra/checks/paths.py) — 켜져 있으면 그 기술의 방식이 있어야, 꺼져 있으면 환경에서 전부 없어야(11/23 사용자 원칙)
# {feat:X}는 X가 켜져 있을 때만, {nofeat:X}는 꺼져 있을 때만 그 줄을 검사(나머지는 건너뜀)

# ---- 항상: 자체 설계 디코이(db-backup-01) PG가 응답(관문이 켜져 있어도 페이로드는 PG로, 꺼져 있으면 남은 TPROXY 규칙이 없어야 닿음)
app-01 | has | timeout 3 bash -c 'exec 3<>/dev/tcp/{ip:db-backup-01}/5432; printf "\000\000\000\010\004\322\026\057" >&3; head -c1 <&3' | ^[NS] | db-backup-01 PG 응답(SSLRequest → N/S)

# ---- Attivo 연결 테이블: 핸드셰이크만 한 연결(web-01 → 디코이 5432) + 디코이 페이로드 관문
web-01 | has | ss -tanH state established dst {ip:db-backup-01}:5432{feat:conntable} | {ip:db-backup-01}:5432 | [Attivo 켬] web-01 연결 테이블에 디코이 연결
db-backup-01 | has | nft list tables{feat:conntable} | local_gate | [Attivo 켬] 디코이 페이로드 관문
web-01 | hasnt | ss -tanH state established dst {ip:db-backup-01}:5432{nofeat:conntable} | {ip:db-backup-01}:5432 | [Attivo 끔] 연결 테이블에 디코이 연결 없음
db-backup-01 | hasnt | nft list tables{nofeat:conntable} | local_gate | [Attivo 끔] 관문 규칙 없음
db-backup-01 | hasnt | ip rule show{nofeat:conntable} | fwmark 0x1 lookup 100 | [Attivo 끔] 관문 fwmark 규칙 없음

# ---- Illusive 맥락 기반 미끼(T1·T2·T5 표본)
web-01 | has | grep -h REPORT_DB_URL= /srv/app/.env{feat:breadcrumbs} | REPORT_DB_URL=\S+:\S+@ | [Illusive 미끼 켬] T1 .env 미끼 DB URL
web-01 | has | cat /home/deploy/.ssh/config{feat:breadcrumbs} | db-backup-01 | [Illusive 미끼 켬] T2 ssh config 미끼
web-01 | hasnt | grep -h REPORT_DB_URL= /srv/app/.env{nofeat:breadcrumbs} | REPORT_DB_URL=\S+:\S+@ | [Illusive 미끼 끔] T1 없음
web-01 | hasnt | cat /home/deploy/.ssh/config{nofeat:breadcrumbs} | db-backup-01 | [Illusive 미끼 끔] T2 없음
web-01 | hasnt | cat /etc/systemd/system/report-sync.service{nofeat:breadcrumbs} | SYNC_DB_URL=\S+://\S+:\S+@ | [Illusive 미끼 끔] T5 서비스에 미끼 계정 없음

# ---- Illusive 트랩 서버 중계
app-01 | has | nft list table ip local_fwd{feat:trap} | tcp dport {trap:app-01:port} .*dnat | [트랩 켬] app-01 빈 포트 → 트랩
app-01 | hasnt | nft list table ip local_fwd{nofeat:trap} | dnat to 169\.254\.200\.1 | [트랩 끔] app-01 넘기는 포트 없음
{farm} | hasnt | machinectl list --no-legend{nofeat:trap} | trap- | [트랩 끔] 팜 트랩 컨테이너 없음

# ---- Acalvio 투영(자세한 것은 paths·attacker·inside 명세)
{sensor} | hasnt | cat /etc/relay/projections{nofeat:projection} | \S | [투영 끔] 센서 투영 목록 비어 있음
{farm} | hasnt | ip -br link{nofeat:projection} | ^relay | [투영 끔] 팜 relay 터널 없음
