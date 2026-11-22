#!/usr/bin/env bash
# stg-01 역할 — 옛 스테이징(2024-06 구축, 2025-05-12 마지막 배포 뒤 안 씀, 2026-11 재구축 때 같이 옮겨짐)
# 팜에서 root로, build.sh 다음에. 패키지 설치는 컨테이너를 멈추고 팜의 네트워크로 한다(컨테이너 망은 투영 주소뿐)
#   sudo ./role.sh <배포 묶음 디렉터리> <db-backup-01 주소> <db-backup-01 ed25519 호스트 공개키 파일>
# 배포 묶음: app/(build_history.py --until 12 결과, .git 포함), base/postgresql/, carryover/make_carryover.py
set -euo pipefail
B=${1:?배포 묶음}; DBB_IP=${2:?db-backup-01 주소}; DBB_KEY=${3:?db-backup-01 호스트 공개키}
NAME=stg-01; ROOT=/var/lib/machines/$NAME
NS=(systemd-nspawn -q --settings=false --register=no --resolv-conf=bind-uplink -D "$ROOT" --pipe --)
BUILT="2024-06-05 16:12:09"          # 스테이징 첫 구축(운영보다 1주 먼저)
LAST_DEPLOY="2025-05-12 13:58:31"    # 마지막 배포(의존성 업데이트 커밋 2025-05-12 11:47 다음)
stamp() { touch -h -d "$1" "${@:2}"; }

systemctl stop systemd-nspawn@$NAME 2>/dev/null || true

# ---- 패키지: 같은 회사 서버와 같은 패치 수준(debootstrap은 출시판만 깐다 → SSH 배너가 달라짐, 11/22 실측)
"${NS[@]}" bash -c 'export DEBIAN_FRONTEND=noninteractive; apt-get update -q && apt-get -y -q full-upgrade &&
  apt-get install -y -q nginx postgresql-16 python3-venv auditd clamav unattended-upgrades logrotate cron >/dev/null'

# ---- 계정: EC2 기본 ubuntu + 앱 계정 deploy(web-01과 같은 이름 규칙)
"${NS[@]}" bash -c 'id ubuntu >/dev/null 2>&1 || useradd -m -s /bin/bash -u 1000 -G sudo,adm ubuntu
  id deploy >/dev/null 2>&1 || useradd -m -s /bin/bash -u 1001 deploy'

# ---- /srv/app: 2025-05-12 커밋까지의 이력, 개발자가 git push로 배포(작업 트리 바로 갱신)
rm -rf "$ROOT/srv/app"; install -d "$ROOT/srv"
cp -a "$B/app" "$ROOT/srv/app"
git -C "$ROOT/srv/app" config receive.denyCurrentBranch updateInstead
cat > "$ROOT/srv/app/.env" <<EOF
# 스테이징
SECRET_KEY=$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | cut -c1-40)
DATABASE_URL=postgresql+psycopg://moayeyak:$(head -c 18 /dev/urandom | base64 | tr -d '/+=')@localhost:5432/moayeyak
RECEIPT_DIR=/srv/app/var/receipts
REPORT_DB_URL=
EOF
install -d "$ROOT/srv/app/var/receipts"
"${NS[@]}" bash -c 'chown -R deploy:deploy /srv/app && chmod 600 /srv/app/.env
  runuser -u deploy -- python3 -m venv /srv/app/.venv &&
  runuser -u deploy -- /srv/app/.venv/bin/pip install -q -r /srv/app/requirements.txt'
install -m 0644 "$ROOT/srv/app/deploy/moayeyak.service" "$ROOT/etc/systemd/system/moayeyak.service"
install -m 0644 "$ROOT/srv/app/deploy/nginx-moayeyak.conf" "$ROOT/etc/nginx/sites-available/moayeyak"
ln -sf /etc/nginx/sites-available/moayeyak "$ROOT/etc/nginx/sites-enabled/moayeyak"
rm -f "$ROOT/etc/nginx/sites-enabled/default"
"${NS[@]}" systemctl enable moayeyak nginx postgresql >/dev/null 2>&1

# ---- PG: 세 서버와 같은 공통 설정(base/postgresql)
conf_d=$(ls -d "$ROOT"/etc/postgresql/*/main/conf.d | head -1)
install -m 0644 "$B/base/postgresql/50-logging.conf" "$B/base/postgresql/50-listen.conf" "$conf_d/"
hba="${conf_d%/conf.d}/pg_hba.conf"; line="host    all             all             10.0.0.0/16             scram-sha-256"
grep -qxF "$line" "$hba" || echo "$line" >> "$hba"
"${NS[@]}" chown -R postgres:postgres "${conf_d#$ROOT}"

# ---- deploy 홈: 마지막 배포 때까지의 흔적. db-backup-01에서 덤프를 가져와 복원(11/22 결정, 새 미끼 키 없음)
H=$ROOT/home/deploy
install -d -m 0700 "$H/.ssh"
printf '%s %s\n' "$DBB_IP" "$(awk '{print $1, $2}' "$DBB_KEY")" > "$H/.ssh/known_hosts.plain"
ssh-keygen -H -f "$H/.ssh/known_hosts.plain" >/dev/null 2>&1; mv "$H/.ssh/known_hosts.plain" "$H/.ssh/known_hosts"; rm -f "$H/.ssh/known_hosts.plain.old"
cat > "$H/.bash_history" <<'EOF'
cd /srv/app
git log --oneline -3
sudo systemctl status moayeyak
curl -sI http://127.0.0.1/
exit
cd /srv/app && git log --oneline -1
.venv/bin/pip install -r requirements.txt
sudo systemctl restart moayeyak
journalctl -u moayeyak -n 20 --no-pager
exit
scp ubuntu@db-backup-01:/backup/dumps/moayeyak-20241125.sql.gz ~/
dropdb moayeyak; createdb -O moayeyak moayeyak
gunzip -c ~/moayeyak-20241125.sql.gz | psql -q moayeyak
rm ~/moayeyak-20241125.sql.gz
cd /srv/app && git log --oneline -1
.venv/bin/pip install -r requirements.txt
sudo systemctl restart moayeyak
exit
cd /srv/app && git log --oneline -1
sudo systemctl reload nginx
curl -sI http://127.0.0.1/static/style.css | grep -i cache
exit
scp ubuntu@db-backup-01:/backup/dumps/moayeyak-20250512.sql.gz ~/
sudo -u postgres dropdb moayeyak
sudo -u postgres createdb -O moayeyak moayeyak
gunzip -c ~/moayeyak-20250512.sql.gz | sudo -u postgres psql -q moayeyak
cd /srv/app && git log --oneline -1
.venv/bin/pip install -r requirements.txt
sudo systemctl restart moayeyak
curl -s http://127.0.0.1/stores | head -20
exit
EOF
grep -q ' db-backup-01$' "$ROOT/etc/hosts" || printf '%s db-backup-01\n' "$DBB_IP" >> "$ROOT/etc/hosts"
# 히스토리의 sudo: 앱 재시작·로그 보기, DB 작업은 postgres로(개발자가 ssh -A로 들어와 덤프를 가져옴 — 키는 남기지 않음)
cat > "$ROOT/etc/sudoers.d/deploy" <<'EOF'
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart moayeyak, /usr/bin/systemctl status moayeyak, /usr/bin/systemctl reload nginx, /usr/bin/journalctl
deploy ALL=(postgres) NOPASSWD: ALL
EOF
chmod 440 "$ROOT/etc/sudoers.d/deploy"; stamp "2024-06-05 16:44:10" "$ROOT/etc/sudoers.d/deploy"

# ---- 컨테이너 안에서 PG를 띄워 2025-05-12 덤프를 만들고 복원 상태로 남긴다
install -d "$ROOT/root/.c"; cp "$B/carryover/make_carryover.py" "$ROOT/root/.c/"
systemctl start systemd-nspawn@$NAME
for i in $(seq 60); do systemd-run -M $NAME -q --wait -P pg_isready -q 2>/dev/null && break; sleep 1; done
systemd-run -M $NAME -q --wait -P python3 -I /root/.c/make_carryover.py --dump-at 2025-05-12 --dump-out /home/deploy/moayeyak-20250512.sql.gz --keep-db moayeyak
rm -rf "$ROOT/root/.c"
PW=$(sed -n 's|^DATABASE_URL=postgresql+psycopg://moayeyak:\([^@]*\)@.*|\1|p' "$ROOT/srv/app/.env")
systemd-run -M $NAME -q --wait -P runuser -u postgres -- psql -qX -c "ALTER ROLE moayeyak LOGIN PASSWORD '$PW';" >/dev/null
systemd-run -M $NAME -q --wait -P chown -R deploy:deploy /home/deploy
systemd-run -M $NAME -q --wait -P systemctl restart moayeyak nginx

# ---- 시각: 첫 구축·마지막 배포에 맞춘다(재구축 때 rsync -a로 옮김 → mtime 보존, ctime은 재구축일)
stamp "$BUILT" "$ROOT"/etc/ssh/ssh_host_* "$H/.bashrc" "$H/.profile" "$H/.bash_logout" "$ROOT/home/ubuntu"/.[bp]*
stamp "2024-06-05 16:40:22" "$ROOT/etc/systemd/system/moayeyak.service" "$ROOT/etc/nginx/sites-available/moayeyak"
stamp "2025-05-12 13:21:07" "$H/.ssh/known_hosts"
find "$ROOT/srv/app/.venv" -exec touch -h -d "$LAST_DEPLOY" {} +
find "$ROOT/srv/app/.git" "$ROOT/srv/app" -maxdepth 0 -exec touch -h -d "2025-05-12 13:57:58" {} +
find "$ROOT/srv/app/.git" -exec touch -h -d "2025-05-12 13:57:58" {} +
stamp "2024-06-05 16:31:44" "$ROOT/srv/app/.env" "$ROOT/srv/app/var" "$ROOT/srv/app/var/receipts"
stamp "2025-05-12 13:24:52" "$H/moayeyak-20250512.sql.gz"
stamp "2025-05-12 14:02:16" "$H/.bash_history" "$H/.ssh" "$H"
echo "stg-01 role ok: $(systemd-run -M $NAME -q --wait -P sh -c 'systemctl is-active moayeyak nginx postgresql ssh | tr "\n" " "')"
