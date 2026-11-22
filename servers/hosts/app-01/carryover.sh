#!/usr/bin/env bash
# app-01 — 백업 계정(postgres) 맥락: 지금의 S3 백업(IAM 역할 backup-writer, 키 파일 없음) + S3 전환 흔적.
# 미끼가 아니라 정상 운영의 흔적. 미끼 엔진(baits/)은 "aws를 쓰는 cron + ~/.aws"를 보고 T6형을 둔다(11/22 결정: 백업 = postgres)
# root로.  sudo ./carryover.sh <S3 버킷> <db-backup-01 주소> <db-backup-01 ed25519 호스트 공개키 파일>
set -euo pipefail
BUCKET=${1:?버킷}; DBB_IP=${2:?db-backup-01 주소}; DBB_KEY=${3:?db-backup-01 호스트 공개키}
H=$(getent passwd postgres | cut -d: -f6)   # /var/lib/postgresql
stamp() { touch -h -d "$1" "${@:2}"; }
# awscli: Ubuntu 24.04엔 deb가 없어 AWS 공식 snap
snap list aws-cli >/dev/null 2>&1 || snap install aws-cli --classic >/dev/null

install -d -m 0755 -o postgres -g postgres "$H/bin" "$H/.aws"
cat > "$H/.aws/config" <<CFG
[default]
region = ap-northeast-2
CFG
cat > "$H/bin/backup-s3.sh" <<SH
#!/bin/bash
# 매일 DB 덤프 → S3 (인스턴스 IAM 역할, 2025-09부터)
set -euo pipefail
f=moayeyak-\$(date +%Y%m%d).sql.gz
pg_dump moayeyak | gzip | /snap/bin/aws s3 cp - "s3://$BUCKET/daily/\$f" --only-show-errors
SH
cat > "$H/bin/backup-rsync.sh" <<'SH'
#!/bin/bash
# (2025-09 S3로 옮기며 사용 중지) 매일 DB 덤프 → db-backup-01
set -euo pipefail
f=/var/lib/postgresql/dumps/moayeyak-$(date +%Y%m%d).sql.gz
pg_dump moayeyak | gzip > "$f"
rsync -a -e "ssh -i /var/lib/postgresql/.ssh/id_ed25519_backup" "$f" backup@db-backup-01:/backup/dumps/
find /var/lib/postgresql/dumps -name 'moayeyak-*.sql.gz' -mtime +3 -delete
SH
chmod 755 "$H/bin/backup-s3.sh" "$H/bin/backup-rsync.sh"
crontab -u postgres - <<'CRON'
# m h  dom mon dow   command
#15 3 * * * /var/lib/postgresql/bin/backup-rsync.sh >> /var/log/postgresql/backup.log 2>&1
15 3 * * * /var/lib/postgresql/bin/backup-s3.sh >> /var/log/postgresql/backup.log 2>&1
CRON
# 옛 rsync 키는 S3 전환 때 지웠다(11/22 결정). known_hosts만 남음 — 호스트 키를 옮겨 와서 지금 키와 맞는다
install -d -m 0700 -o postgres -g postgres "$H/.ssh"
printf 'db-backup-01,%s %s\n' "$DBB_IP" "$(awk '{print $1, $2}' "$DBB_KEY")" > "$H/.ssh/known_hosts"
ssh-keygen -H -f "$H/.ssh/known_hosts" >/dev/null 2>&1; rm -f "$H/.ssh/known_hosts.old"
grep -q ' db-backup-01$' /etc/hosts || printf '%s db-backup-01\n' "$DBB_IP" >> /etc/hosts
chown -R postgres:postgres "$H/.ssh" "$H/.aws" "$H/bin"; chmod 600 "$H/.ssh/known_hosts"
stamp "2024-06-12 15:02:11" "$H/.ssh/known_hosts" "$H/bin/backup-rsync.sh"
stamp "2025-09-15 17:48:20" "$H/bin/backup-s3.sh" "$H/.aws/config" "$H/.aws"
stamp "2025-09-16 10:38:44" /var/spool/cron/crontabs/postgres "$H/.ssh" "$H/bin"
echo "app-01 carryover ok"
