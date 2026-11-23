# 디코이 안쪽(infra/checks/paths.py) — 공격자가 들어간 뒤 보는 것. 환경 중립: "디코이 = 진짜 서버(app-01)"를 그 자리에서 비교(samehost)
# 접속: 프로필 access.run_decoy(로컬은 web-01 점프 — 디코이 auth.log에 web-01 출발 ubuntu 로그인이 남는다 = 측정 흔적)
{proj:stg:ip} ~ app-01 | samehost | systemd-detect-virt | ^(\S+)$ | stg 가상화 종류 = app-01(컨테이너면 systemd-nspawn — 11/22 B7)
{proj:stg:ip} ~ app-01 | samehost | auditctl -s | ^(enabled \d) | stg auditd = app-01(컨테이너는 불가 — 11/22 D4)
{proj:stg:ip} ~ app-01 | samehost | auditctl -l | (-S execve -F auid!=-1 -F key=user-cmd) | stg 공통 감사 규칙(로그인 세션 명령) = app-01
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
{proj:stg:ip} | has | systemctl is-active moayeyak nginx postgresql | ^active\nactive\nactive$ | stg 역할 서비스(앱·nginx·PG)
{proj:stg:ip} | hasnt | grep -rhE "touch -d|make_carryover|nspawn|guest-build" /var/log/auth.log /var/log/audit/ | . | stg 빌드 명령이 게스트 로그에 없음
# 출발점·패치 상태가 진짜 서버와 같은가(블렌딩 — 이미지 serial, 저장소 파일, 설치된 커널 목록). 가정하지 말고 잰다(11/23)
{proj:stg:ip} ~ app-01 | samehost | cat /etc/cloud/build.info | serial: (\S+) | stg 출발 이미지 serial = app-01
{proj:stg:ip} ~ app-01 | samehost | md5sum /etc/apt/sources.list.d/ubuntu.sources | ^([0-9a-f]{32}) | stg 저장소 파일 = app-01(빌드용 Snapshot 흔적 없음, cloud-init 템플릿과 이미지 원본이 같은가)
{proj:stg:ip} ~ app-01 | samehost | ls /boot/vmlinuz-* | (?s)(/boot/vmlinuz-.*\S) | stg 설치된 커널 목록 = app-01
{proj:stg:ip} ~ app-01 | samehost | auditctl -l|md5sum | ^([0-9a-f]{32}) | stg 감사 규칙 전체 = app-01(빌드 로그의 "line 23 오류"가 진짜 서버와 같은 결과인가)
{proj:stg:ip} ~ app-01 | samehost | systemctl is-active moa-notify | ^(\S+)$ | stg 경보 데몬(moa-notify) = app-01(세 서버 공통 — 디코이에만 없으면 단서이자 탐지 공백, 11/23)
{proj:stg:ip} ~ web-01 | samehost | free -m | ^Mem:\s+(\d+) | stg 메모리(free -m) = 같은 구간 진짜 서버(web-01). /proc/meminfo는 4kB 차이(NIC 수 등 하드웨어 차이 — 기록, 11/23)
# dev-01(int 구간 — 이웃 app-01)
{proj:dev:ip} ~ app-01 | samehost | systemd-detect-virt | ^(\S+)$ | dev 가상화 종류 = app-01
{proj:dev:ip} ~ app-01 | samehost | auditctl -s | ^(enabled \d) | dev auditd = app-01
{proj:dev:ip} ~ app-01 | samehost | cloud-id | ^(\S+)$ | dev cloud-id = app-01
{proj:dev:ip} ~ app-01 | samehost | uname -r | ^(\S+)$ | dev 실행 커널 = app-01
{proj:dev:ip} ~ app-01 | samehost | ls /boot/vmlinuz-* | (?s)(/boot/vmlinuz-.*\S) | dev 설치된 커널 목록 = app-01
{proj:dev:ip} ~ app-01 | samehost | md5sum /etc/apt/sources.list.d/ubuntu.sources | ^([0-9a-f]{32}) | dev 저장소 파일 = app-01
{proj:dev:ip} ~ app-01 | samehost | cat /etc/cloud/build.info | serial: (\S+) | dev 출발 이미지 serial = app-01
{proj:dev:ip} ~ app-01 | samehost | free -m | ^Mem:\s+(\d+) | dev 메모리(free -m) = app-01
{proj:dev:ip} ~ app-01 | samehost | systemctl is-active moa-notify | ^(\S+)$ | dev 경보 데몬 = app-01
{proj:dev:ip} ~ app-01 | samehost | auditctl -l|md5sum | ^([0-9a-f]{32}) | dev 감사 규칙 전체 = app-01
{proj:dev:ip} | has | ip -o link show {if:app-01} | link/ether {proj:dev:mac} | dev NIC 이름 = app-01, MAC = 이웃 ARP 값
{proj:dev:ip} | has | hostname | ^{proj:dev:name}$ | dev hostname
{proj:dev:ip} | hasnt | cat /var/lib/cloud/instance/user-data.txt | runcmd|base\.tgz|power_state|build\.sh | dev user-data에 빌드 내용 없음
{proj:dev:ip} | has | systemctl is-active postgresql | ^active$ | dev 개발 DB(PG)
