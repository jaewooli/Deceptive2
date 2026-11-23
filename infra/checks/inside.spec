# 디코이 안쪽(infra/checks/paths.py) — 공격자가 들어간 뒤 보는 것. 환경 중립: "디코이 = 진짜 서버(app-01)"를 그 자리에서 비교(samehost)
# 접속: 프로필 access.run_decoy(로컬은 web-01 점프 — 디코이 auth.log에 web-01 출발 ubuntu 로그인이 남는다 = 측정 흔적)
{proj:stg:ip} ~ app-01 | samehost | systemd-detect-virt | ^(\S+)$ | stg 가상화 종류 = app-01(컨테이너면 systemd-nspawn — 11/22 B7)
{proj:stg:ip} ~ app-01 | samehost | auditctl -s | ^(enabled \d) | stg auditd = app-01(컨테이너는 불가 — 11/22 D4)
{proj:stg:ip} ~ app-01 | samehost | auditctl -l | (auid>=1000 .*-k \S+) | stg 공통 감사 규칙(로그인 세션 명령) = app-01
{proj:stg:ip} ~ app-01 | samehost | cloud-id | ^(\S+)$ | stg cloud-id = app-01
{proj:stg:ip} ~ app-01 | samehost | uname -r | ^(\S+)$ | stg 실행 커널 = app-01(블렌딩 스냅숏)
{proj:stg:ip} ~ app-01 | samehost | dpkg-query -W -f '${Version}' openssh-server | ^(\S+)$ | stg openssh 버전 = app-01
{proj:stg:ip} ~ app-01 | samehost | timedatectl show -p Timezone --value | ^(\S+)$ | stg 시간대 = app-01
{proj:stg:ip} ~ app-01 | samehost | nproc | ^(\d+)$ | stg vCPU 수 = app-01
{proj:stg:ip} ~ app-01 | samehost | cat /sys/class/dmi/id/sys_vendor /sys/class/dmi/id/product_name | (?s)^(.+?)\s*$ | stg DMI = app-01
{proj:stg:ip} ~ app-01 | samehost | snap list amazon-ssm-agent | ^(amazon-ssm-agent) | stg 공통 에이전트(SSM) = app-01
{proj:stg:ip} ~ app-01 | samehost | systemctl is-active amazon-cloudwatch-agent | ^(\S+)$ | stg 공통 에이전트(CloudWatch) = app-01
{proj:stg:ip} ~ app-01 | samehost | cat /etc/cron.d/clamav-scan | (clamscan.*) | stg ClamAV 검사 cron = app-01
{proj:stg:ip} | has | ip -o link show {if:app-01} | link/ether {proj:stg:mac} | stg NIC 이름 = app-01 NIC 이름, MAC = 이웃 ARP 값
{proj:stg:ip} | has | hostname | ^{proj:stg:name}$ | stg hostname
{proj:stg:ip} | hasnt | lsblk -dno NAME | ^sr1$ | stg CD-ROM 하나(seed ISO 흔적 없음)
{proj:stg:ip} | hasnt | cat /var/lib/cloud/instance/user-data.txt | runcmd|base\.tgz|power_state | stg user-data에 빌드 내용 없음
{proj:stg:ip} | hasnt | ls /etc/apt/apt.conf.d | 50-build-snapshot | stg 빌드용 스냅숏 설정 없음
{proj:stg:ip} | has | systemctl is-active moayeyak nginx postgresql | \Aactive\nactive\nactive | stg 역할 서비스(앱·nginx·PG)
{proj:stg:ip} | hasnt | grep -rhE "touch -d|make_carryover|nspawn|guest-build" /var/log/auth.log /var/log/audit/audit.log | . | stg 빌드 명령이 게스트 로그에 없음
