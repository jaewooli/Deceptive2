#!/usr/bin/env bash
# web-01 — 재구축(2026-11) 때 옛 서버에서 옮겨 온 것 + 재구축 뒤 배포 확인. root로, webapp/deploy/install.sh 다음에.
# 미끼가 아니라 "진짜로 쓰인 정상 서버"의 흔적이다. 미끼 엔진(baits/)은 이 맥락을 읽고 배치를 정한다(11/22).
#   sudo ./carryover.sh <묶음 디렉터리> <app-01 주소> <app-01 ed25519 호스트 공개키 파일> <DB 비밀번호 파일> [재구축 시각]
# 묶음: app/(build_history.py 전체 결과, .git 포함)
set -euo pipefail
B=${1:?묶음}; APP_IP=${2:?app-01 주소}; APP_KEY=${3:?app-01 호스트 공개키}; PWF=${4:?DB 비밀번호 파일}
REBUILT=${5:-$(date '+%F %T')}
H=/home/deploy
stamp() { touch -h -d "$1" "${@:2}"; }
export DEBIAN_FRONTEND=noninteractive
dpkg -s postgresql-client-16 >/dev/null 2>&1 || apt-get install -y -q postgresql-client-16 >/dev/null

# ---- 이름 해석: 작은 회사라 사설 DNS 대신 /etc/hosts
grep -q ' app-01$' /etc/hosts || printf '%s app-01\n' "$APP_IP" >> /etc/hosts

# ---- /srv/app: 전체 이력, 개발자가 git push로 배포(작업 트리 바로 갱신)
systemctl stop moayeyak 2>/dev/null || true
keep=$(mktemp -d); [ -d /srv/app/.venv ] && mv /srv/app/.venv "$keep/"
rm -rf /srv/app; cp -a "$B/app" /srv/app; [ -d "$keep/.venv" ] && mv "$keep/.venv" /srv/app/; rmdir "$keep"
git -C /srv/app config receive.denyCurrentBranch updateInstead
cat > /srv/app/.env <<EOF
# /srv/app/.env (systemd EnvironmentFile)
SECRET_KEY=$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | cut -c1-40)
DATABASE_URL=postgresql+psycopg://moayeyak:$(cat "$PWF")@app-01:5432/moayeyak
RECEIPT_DIR=/srv/app/var/receipts

# 월간 리포트 (S3 이전 후 비활성)
REPORT_ENABLED=false
REPORT_DB_URL=
EOF
install -d /srv/app/var/receipts
chown -R deploy:deploy /srv/app; chmod 600 /srv/app/.env
runuser -u deploy -- /srv/app/.venv/bin/pip install -q -r /srv/app/requirements.txt

# ---- deploy 홈: 배포·DB 확인. 개발자가 ssh -A로 들어와 app-01에 들름(키는 남기지 않음)
install -d -m 0700 -o deploy -g deploy "$H/.ssh"
printf '%s %s\n' "$APP_IP" "$(awk '{print $1, $2}' "$APP_KEY")" > "$H/.ssh/known_hosts"
printf 'app-01 %s\n' "$(awk '{print $1, $2}' "$APP_KEY")" >> "$H/.ssh/known_hosts"
ssh-keygen -H -f "$H/.ssh/known_hosts" >/dev/null 2>&1; rm -f "$H/.ssh/known_hosts.old"
cat > "$H/.bash_history" <<'EOF'
cd /srv/app
git log --oneline -5
sudo systemctl status moayeyak
curl -sI http://127.0.0.1/
exit
cd /srv/app && git log --oneline -1
.venv/bin/pip install -r requirements.txt
sudo systemctl restart moayeyak
journalctl -u moayeyak -n 30 --no-pager
exit
psql -h app-01 -U moayeyak moayeyak
exit
cd /srv/app && git log --oneline -1
sudo systemctl restart moayeyak
curl -s http://127.0.0.1/stores | head -20
exit
ssh ubuntu@app-01 df -h
ssh ubuntu@app-01 'sudo -u postgres psql -c "select pg_size_pretty(pg_database_size(current_database()))" moayeyak'
exit
cd /srv/app && git log --oneline -3
git show --stat HEAD
sudo systemctl restart moayeyak
journalctl -u moayeyak -n 20 --no-pager
exit
cd /srv/app && git log --oneline -1
.venv/bin/pip install -r requirements.txt
sudo systemctl restart moayeyak
psql -h app-01 -U moayeyak moayeyak -c 'select count(*) from reservations'
exit
cd /srv/app && git status
git log --oneline -1
sudo systemctl status moayeyak
curl -sI http://127.0.0.1/
psql -h app-01 -U moayeyak moayeyak -c 'select count(*) from reservations'
exit
EOF
cat > "$H/.psql_history" <<'EOF'
\dt
select count(*) from reservations;
select name, is_active from stores order by id;
select status, count(*) from reservations group by 1;
\d reservations
select count(*) from reservations where updated_at > created_at;
EOF
cat > /etc/sudoers.d/deploy <<'EOF'
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart moayeyak, /usr/bin/systemctl status moayeyak, /usr/bin/systemctl reload nginx, /usr/bin/journalctl
EOF
chmod 440 /etc/sudoers.d/deploy
chown deploy:deploy "$H/.ssh/known_hosts" "$H/.bash_history" "$H/.psql_history"; chmod 600 "$H/.bash_history" "$H/.psql_history" "$H/.ssh/known_hosts"

# ---- 시각: 옮겨 온 것은 옛 날짜, 재구축 뒤 배포 확인은 재구축일
stamp "2024-06-12 15:40:02" "$H/.bashrc" "$H/.profile" "$H/.bash_logout" /etc/sudoers.d/deploy 2>/dev/null || true
stamp "2024-06-14 10:21:44" "$H/.ssh"
stamp "2025-10-22 09:12:31" "$H/.psql_history"
stamp "2025-09-15 18:33:50" /srv/app/.env
find /srv/app/.git -exec touch -h -d "2026-11-18 16:41:30" {} +
stamp "2026-11-18 16:41:30" /srv/app
stamp "$REBUILT" "$H/.bash_history" "$H/.ssh/known_hosts" "$H"
systemctl start moayeyak
sleep 2
echo "web-01 carryover ok: $(systemctl is-active moayeyak) $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/stores)"
