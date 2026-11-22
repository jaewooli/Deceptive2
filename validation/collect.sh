#!/usr/bin/env bash
# 구별 단서 수집 (checks.md 항목별 원자료). 대상 서버에서 root로, 파일을 남기지 않게 stdin으로 실행한다.
#   로컬 VM : infra/local-vm/vm.sh ssh 'sudo bash -s' < validation/collect.sh > out/validation/<날짜>/<호스트>.txt
#   AWS     : 같은 내용을 SSM Run Command(AWS-RunShellScript)로 (11/29)
# 읽기 전용: 설정·서비스·파일을 바꾸지 않는다. 단, 측정 자체가 남기는 흔적은 막을 수 없다
#   - SSH/SSM 로그인 기록(auth.log, wtmp), 로그인 세션 execve(auditd 50-user-cmd)
#   - C5: postgres 로컬 소켓 접속 1회(log_connections → moa-notify가 볼 수 있음)
# 외부에서 보는 응답(E1·E2)은 probe.py가 따로 잰다(공격자 시점).
# 출력: "### <ID>" 구역마다 원자료. 판정은 compare.py
set -uo pipefail
export LC_ALL=C TZ=Asia/Seoul
sec() { printf '\n### %s\n' "$1"; }
homes() { getent passwd | awk -F: '$7 !~ /(nologin|false|sync)$/ && $6 ~ /^\/(home|root|var\/backups|backup)/ {print $1":"$6}'; }
ts() { stat -c '%y %n' "$@" 2>/dev/null | sed 's/\.[0-9]* / /'; }
zc() { zcat -f "$@" 2>/dev/null; }

sec META
echo "hostname=$(hostname)"
echo "collected_at=$(date -Iseconds)"
. /etc/os-release; echo "os=$PRETTY_NAME"
echo "kernel=$(uname -r)"

# ---------------- A. 사용 흔적
sec A1
last -F -w -f /var/log/wtmp 2>/dev/null | tail -n 25
ls -l --time-style=+%F /var/log/wtmp* /var/log/btmp* 2>/dev/null
echo "logins_total=$(last -w 2>/dev/null | grep -cvE '^(reboot|wtmp|$)')"

sec A2
lastlog 2>/dev/null | grep -v 'Never logged in' || lslogins -o USER,UID,LAST-LOGIN 2>/dev/null

sec A3
for h in $(homes); do
  u=${h%%:*}; d=${h#*:}; f=$d/.bash_history
  if [ -f "$f" ]; then echo "$u lines=$(wc -l < "$f") mtime=$(stat -c %y "$f" | cut -d. -f1)"; tail -n 3 "$f" | sed "s/^/  $u> /"
  else echo "$u 없음"; fi
done

sec A4
for h in $(homes); do
  u=${h%%:*}; d=${h#*:}
  echo "$u $(find "$d" -xdev -type f -printf '%TY-%Tm\n' 2>/dev/null | sort | uniq -c | awk '{printf "%s:%s ", $2, $1}')"
done

sec A5
echo "rotated_files=$(find /var/log -type f -regextype posix-extended -regex '.*\.[0-9]+(\.gz)?$' | wc -l)"
# weekly·rotate 4(배포판 기본)로 한 달 넘게 켜져 있었다면 .4.gz까지 찬 로그가 있다
echo "full_sets=$(find /var/log -type f -name '*.4.gz' | wc -l)"
echo "oldest:"; find /var/log -type f -printf '%TY-%Tm-%Td %p\n' 2>/dev/null | sort | head -n 3
grep -hE '^\s*(weekly|daily|monthly|rotate)\b' /etc/logrotate.conf | tr -s ' ' | sort | uniq -c

sec A6
journalctl --list-boots --no-pager 2>/dev/null | sed -n '1p;2p;$p'
echo "boots=$(journalctl --list-boots --no-pager 2>/dev/null | tail -n +2 | wc -l)"

sec A7
echo "apt_runs=$(zc /var/log/apt/history.log* | grep -c '^Start-Date')"
echo "apt_first=$(zc /var/log/apt/history.log* | grep '^Start-Date' | awk '{print $2}' | sort | head -1)"
echo "apt_last=$(zc /var/log/apt/history.log* | grep '^Start-Date' | awk '{print $2}' | sort | tail -1)"
echo "dpkg_first=$(zc /var/log/dpkg.log* | awk '{print $1}' | sort | head -1)"
echo "dpkg_last=$(zc /var/log/dpkg.log* | awk '{print $1}' | sort | tail -1)"
echo "unattended_runs=$(ls /var/log/unattended-upgrades/unattended-upgrades.log* 2>/dev/null | wc -l)"

sec A8
echo "uptime_since=$(uptime -s)"
last -x -F reboot 2>/dev/null | head -n 5

sec A9
if [ -d /backup/dumps ]; then
  echo "count=$(find /backup/dumps -type f | wc -l)"
  find /backup/dumps -type f -printf '%TY-%Tm-%Td %s %f\n' | sort | sed -n '1p;$p'
  echo "months=$(find /backup/dumps -type f -printf '%TY-%Tm\n' | sort | uniq -c | awk '{printf "%s:%s ", $2, $1}')"
else echo "/backup/dumps 없음"; fi
df -hT -x tmpfs -x devtmpfs -x squashfs -x overlay 2>/dev/null

sec A10
echo "cron_last=$(zc /var/log/syslog* | grep -E 'CRON\[' | tail -n 1 | cut -c1-120)"
echo "rsync_lines=$(zc /var/log/syslog* /var/log/rsyncd.log* 2>/dev/null | grep -c rsync)"
zc /var/log/rsyncd.log* 2>/dev/null | tail -n 2

# ---------------- B. 구축 흔적
sec B1
ts /var/log/cloud-init.log /var/log/cloud-init-output.log
ls -l --time-style=+%F /var/lib/cloud/instances 2>/dev/null | tail -n +2
head -n 1 /var/log/cloud-init.log 2>/dev/null | cut -c1-80

sec B2
for f in /var/log/auth.log /var/log/syslog; do
  [ -f "$f" ] || continue
  echo "$f utc=$(grep -cE '^[0-9T:.-]+\+00:00' "$f") kst=$(grep -cE '^[0-9T:.-]+\+09:00' "$f") utc_after_kst=$(awk '/^[0-9T:.-]+\+09:00/{k=1} k && /^[0-9T:.-]+\+00:00/{n++} END{print n+0}' "$f") first=$(head -c 32 "$f")"
done

sec B3
dev=$(findmnt -no SOURCE /)
tune2fs -l "$dev" 2>/dev/null | grep -E 'Filesystem created|Last mount time|Mount count'
stat -c 'birth=%w %n' / 2>/dev/null

sec B4
ts /etc/ssh/ssh_host_*_key.pub

sec B5
ts /etc/machine-id /etc/hostname

sec B6
cat /etc/cloud/build.info 2>/dev/null || echo "build.info 없음"
ts /etc/cloud/build.info /var/log/installer 2>/dev/null

# ---------------- C. 연결 흔적
sec C1
for h in $(homes); do
  d=${h#*:}; f=$d/.ssh/known_hosts
  [ -f "$f" ] || continue
  echo "${h%%:*} known_hosts=$(grep -c . "$f") mtime=$(stat -c %y "$f" | cut -d. -f1)"
  ssh-keygen -F db-backup-01 -f "$f" 2>/dev/null | grep -v '^#' | awk '{print $2, $3}' | ssh-keygen -lf - 2>/dev/null | awk -v u="${h%%:*}" '{print "kh", u, $2}'
done
for k in /etc/ssh/ssh_host_*_key.pub; do ssh-keygen -lf "$k" | awk '{print "hostkey", $2}'; done
echo "-- Accepted 로그인 출발지"
zc /var/log/auth.log* | grep -oE 'Accepted \S+ for \S+ from \S+' | awk '{print $4, $6}' | sort | uniq -c

sec C2
for h in $(homes); do
  d=${h#*:}; f=$d/.ssh/authorized_keys
  [ -f "$f" ] && ssh-keygen -lf "$f" 2>/dev/null | awk -v u="${h%%:*}" '{print u, $2, $3}'
done

sec C3
grep -vE '^\s*(#|$)' /etc/hosts
for n in db-backup-01 app-01 web-01; do echo "$n -> $(getent hosts "$n" | awk '{print $1}')"; done

sec C4
ss -Htan state established | awk '{print $3, $4}' | grep -vE '127\.0\.0\.1|\[::1\]' | sort | uniq -c | head -n 20
ip neigh 2>/dev/null | head -n 10

sec C5
if command -v psql >/dev/null; then
  runuser -u postgres -- psql -XAtq -d postgres -c "select datname from pg_database where not datistemplate and datname<>'postgres'" 2>&1 |
  while read -r db; do
    echo "db=$db"
    runuser -u postgres -- psql -XAtq -d "$db" -c "select table_name||'('||string_agg(column_name,',' order by ordinal_position)||')' from information_schema.columns where table_schema='public' group by table_name order by 1" 2>&1 | sed 's/^/  /'
  done
else echo "psql 없음"; fi

sec C6
ls -l --time-style=+%F /etc/rsyncd.conf 2>/dev/null || echo "rsyncd.conf 없음"
echo "rsync $(systemctl is-enabled rsync 2>/dev/null) $(systemctl is-active rsync 2>/dev/null)"
for h in $(homes); do f=${h#*:}/.ssh/authorized_keys; [ -f "$f" ] && echo "rrsync_keys ${h%%:*}=$(grep -c 'rrsync' "$f")"; done
ls -l --time-style=+%F /etc/cron.d/backup-dumps 2>/dev/null

# ---------------- D. 감시 흔적 (app-01과 같아야 함)
sec D1
ps -eo comm= | sort -u | grep -vE '^(kworker|ksoftirqd|migration|rcu_|cpuhp|idle_inject|irq/|scsi_|jbd2|kthreadd|kdevtmpfs|khugepaged|kcompactd|oom_reaper|watchdog|writeback|kblockd|kswapd|ext4|xfs|card|ata_|kauditd|khungtaskd|kintegrityd|ksmd|mm_percpu|netns|pool_|psimon|charger|devfreq|edac|inet_frag|kstrp|tpm|zswap|blkcg|cryptd|hwrng|ipv6|kaluad|kmpath|md$|mld|rcu|slub|kthrotld|acpi|vfio|ttm|nvme|virtio|hv_)'

sec D2
dpkg-query -W -f='${Package}\n' | sort

sec D3
systemctl list-unit-files --state=enabled --no-legend --no-pager | awk '{print $1}' | sort

sec D4
echo "rules=$(auditctl -l 2>/dev/null | wc -l)"
auditctl -l 2>/dev/null | md5sum | cut -c1-12

sec D5
for f in /etc/audit/rules.d/* /etc/audit/auditd.conf /opt/aws/amazon-cloudwatch-agent/etc/agent.json /etc/moa-notify/*; do
  [ -f "$f" ] && echo "$(md5sum < "$f" | cut -c1-12) $f"
done

sec D6
ss -Hltn | awk '{print $4}' | sed -E 's/.*[:.]([0-9]+)$/\1/' | sort -n | uniq | tr '\n' ' '; echo

sec D7
ls /etc/cron.d /etc/cron.daily /etc/cron.weekly 2>/dev/null
for u in $(cut -d: -f1 /etc/passwd); do crontab -l -u "$u" >/dev/null 2>&1 && echo "crontab:$u"; done

sec D8
for f in /etc/rsyslog.conf /etc/rsyslog.d/* /etc/systemd/journald.conf /etc/systemd/journald.conf.d/* /etc/logrotate.conf /etc/logrotate.d/*; do
  [ -f "$f" ] && echo "$(md5sum < "$f" | cut -c1-12) $f"
done

# ---------------- E. 구현 차이 (내부 설정 — 외부 응답은 probe.py)
sec E1
ssh -V 2>&1
sshd -T 2>/dev/null | grep -E '^(port|listenaddress|kexalgorithms|ciphers|macs|hostkeyalgorithms|passwordauthentication|permitrootlogin) ' | sort

sec E2
command -v postgres >/dev/null || ls /usr/lib/postgresql/*/bin/postgres 2>/dev/null
ls /usr/lib/postgresql 2>/dev/null
grep -vE '^\s*(#|$)' /etc/postgresql/*/main/pg_hba.conf 2>/dev/null

sec E3
echo "11/24 다중 주소 이후"

# ---------------- F. 이야기 일관성
sec F1
echo "(A2·A9·A10·C1 날짜를 compare.py에서 교차)"

sec F2
. /etc/os-release; echo "$VERSION_ID $VERSION_CODENAME"
# 빈 /var/log/dist-upgrade 디렉터리는 이미지에 기본으로 있다 → 파일 수로 센다
n=$(find /var/log/dist-upgrade -type f 2>/dev/null | wc -l)
[ "$n" -gt 0 ] && echo "dist-upgrade 기록 ${n}개: $(ls /var/log/dist-upgrade | head -n 3 | tr '\n' ' ')" || echo "dist-upgrade 기록 없음"

sec F3
du -sh /backup 2>/dev/null || echo "/backup 없음"
df -h / | tail -n 1

sec F4
# 용어 목록을 명령 인자로 넘기면 sudo(auth.log)·auditd execve 기록에 그 단어가 남는다(11/22 실측: 측정이 디코이를 오염시킴)
# → 셸 내장 printf로 만들어 파일 기술자로 넘긴다(grep 인자에는 /dev/fd/N만 남음). 영어 + 한국어. 'trap'은 셸 내장 명령과 겹쳐 제외
terms() { printf '%s\n' 'deceptive' 'honeypot' 'honeytoken' 'decoy' 'canary' 'cowrie' 'lure' 'bait' \
  '디코이' '미끼' '함정' '허니팟' '허니토큰' '기만' '가짜'; }
F4_DIRS=(/etc /opt /srv /home /root /usr/local /var/log /var/spool /var/backups /backup)
grep -rIilwF -f <(terms) "${F4_DIRS[@]}" 2>/dev/null | head -n 30
# 호스트 이름 자체에 용어가 들어 있으면(로컬 VM lt-decoy) 그 이름이 퍼진 파일과 다른 원인을 나눈다
echo "hostname=$(hostname)"
echo "-- 호스트 이름을 지운 뒤에도 남는 파일"
grep -rIilwF -f <(terms) "${F4_DIRS[@]}" 2>/dev/null |
  while read -r f; do
    # grep -q는 첫 매치에서 끝나 sed가 SIGPIPE로 죽고, pipefail이 이를 실패로 본다 → 끝까지 센다
    n=$(sed "s/$(hostname)//g" "$f" | grep -ciwF -f <(terms)); [ "${n:-0}" -gt 0 ] && echo "$f ($n줄)"
  done | head -n 30

sec F5
tok=$(curl -s -m 2 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token 2>/dev/null)
if [ -n "$tok" ]; then
  for k in ami-id instance-type local-ipv4; do echo "$k=$(curl -s -m 2 -H "X-aws-ec2-metadata-token: $tok" http://169.254.169.254/latest/meta-data/$k)"; done
else echo "IMDS 없음"; fi

sec F6
getent passwd | awk -F: '$3==0 || $3>=1000 || $7 !~ /(nologin|false|sync)$/ {print $1, $3, $6, $7}'
getent group sudo adm | cut -d: -f1,4
