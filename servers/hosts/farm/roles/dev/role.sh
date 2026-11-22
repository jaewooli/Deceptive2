#!/usr/bin/env bash
# dev 역할(이름은 블렌딩, 예: dev-01) — 옛 개발 서버(11/23 사용자 결정, HANDOFF 11절)
#   2024-09-02 구축(이서연 합류 — 두 개발자가 같은 저장소·개발 DB를 쓰려고) → 2025-05-12 마지막 사용(이날부터 각자 노트북 로컬 개발,
#   같은 날 stg-01도 마지막 배포) → 2026-11 재구축 때 확인 없이 같이 옮겨짐
#   공유 bare 저장소(/srv/git) + 개발자별 clone(remote: origin = 공유, staging = deploy@stg-01, production = deploy@web-01 — 둘 다 git push 배포)
#   개발 DB = 2025-05-12 운영 사본(소규모 팀에서 흔한 관행). 다른 서버로 이어지는 흔적은 remote·known_hosts뿐(개인키는 노트북에 — 새 자격증명 없음)
# 팜에서 root로. ../guest/guest.sh create → offline → 이 스크립트 → seal → online. VM이 꺼진 디스크에 비부팅 nspawn으로만(게스트 로그에 빌드 명령 없음)
#   sudo ./role.sh <배포 묶음> <stg 이름> <stg 주소> <stg 호스트 키 파일> <web-01 주소> <web-01 호스트 키 파일> <db-backup-01 주소> <db-backup-01 호스트 키 파일>
# 배포 묶음: app/(build_history.py --until 12, .git 포함), base/postgresql/, carryover/make_carryover.py
# 패키지(create에 넘김): postgresql-16,python3-venv,git
set -euo pipefail
B=${1:?묶음}; STG=${2:?stg 이름}; STG_IP=${3:?}; STG_KEY=${4:?}; WEB_IP=${5:?}; WEB_KEY=${6:?}; DBB_IP=${7:?}; DBB_KEY=${8:?}
NAME=${GUEST_NAME:-dev-01}; ROOT=/var/lib/machines/$NAME
NS=(systemd-nspawn -q --settings=false --register=no --resolv-conf=bind-uplink -D "$ROOT" --pipe --)
NSP=(systemd-nspawn -q --settings=false --register=no --private-network -D "$ROOT" --pipe --)   # 사설망(루프백만)
BUILT="2024-09-02 10:41:17"
LAST="2025-05-12 14:06:52"          # 이서연의 마지막 세션(13:58 stg-01에 push 다음)
stamp() { touch -h -d "$1" "${@:2}"; }
findmnt -rno SOURCE "$ROOT" >/dev/null || { echo "$ROOT 가 마운트돼 있지 않음 — guest.sh offline $NAME 먼저" >&2; exit 2; }

# ---- 계정: 개발자 2명(커밋 작성자와 같은 사람들). 비밀번호 없음(키 로그인), DB 작업은 postgres로
"${NS[@]}" bash -c 'getent group devs >/dev/null || groupadd -g 1100 devs
  id jihoon >/dev/null 2>&1 || useradd -m -s /bin/bash -u 1001 -G adm,devs -c "Park Jihoon" jihoon
  id seoyeon >/dev/null 2>&1 || useradd -m -s /bin/bash -u 1002 -G adm,devs -c "Lee Seoyeon" seoyeon'
cat > "$ROOT/etc/sudoers.d/devs" <<'EOF'
%devs ALL=(postgres) NOPASSWD: ALL
%devs ALL=(root) NOPASSWD: /usr/bin/systemctl restart postgresql, /usr/bin/journalctl
EOF
chmod 440 "$ROOT/etc/sudoers.d/devs"; stamp "2024-09-02 10:52:40" "$ROOT/etc/sudoers.d/devs"

# ---- 공유 저장소: 2025-05-12까지의 이력(앱 이력 생성기 12단계)
rm -rf "$ROOT/srv/git"; install -d "$ROOT/srv/git"
git clone -q --bare "$B/app" "$ROOT/srv/git/moayeyak.git"
git -C "$ROOT/srv/git/moayeyak.git" config core.sharedRepository group
git -C "$ROOT/srv/git/moayeyak.git" remote remove origin 2>/dev/null || true
"${NS[@]}" bash -c 'chgrp -R devs /srv/git && chmod -R g+rwX /srv/git && find /srv/git -type d -exec chmod g+s {} +'

# ---- 개발자 clone·venv·개발 설정
PW=$(head -c 18 /dev/urandom | base64 | tr -d '/+=')
for u in jihoon seoyeon; do
  H=$ROOT/home/$u
  rm -rf "$H/moayeyak"
  git clone -q "$ROOT/srv/git/moayeyak.git" "$H/moayeyak"
  git -C "$H/moayeyak" remote set-url origin /srv/git/moayeyak.git
  git -C "$H/moayeyak" remote add staging "deploy@$STG:/srv/app" 2>/dev/null || true
  git -C "$H/moayeyak" remote add production deploy@web-01:/srv/app 2>/dev/null || true
  case $u in jihoon) gn="박지훈"; ge=jihoon@moayeyak.example ;; seoyeon) gn="이서연"; ge=seoyeon@moayeyak.example ;; esac
  printf '[user]\n\tname = %s\n\temail = %s\n[pull]\n\trebase = false\n[init]\n\tdefaultBranch = main\n' "$gn" "$ge" > "$H/.gitconfig"
  cat > "$H/moayeyak/.env" <<EOF
# 개발
SECRET_KEY=dev-$(head -c 12 /dev/urandom | base64 | tr -d '/+=')
DATABASE_URL=postgresql+psycopg://moayeyak:$PW@localhost:5432/moayeyak_dev
RECEIPT_DIR=/home/$u/moayeyak/var/receipts
REPORT_DB_URL=
EOF
  install -d "$H/moayeyak/var/receipts"
done
"${NS[@]}" bash -c 'for u in jihoon seoyeon; do chown -R $u:$u /home/$u; chmod 600 /home/$u/moayeyak/.env
  runuser -u $u -- python3 -m venv /home/$u/moayeyak/.venv &&
  runuser -u $u -- /home/$u/moayeyak/.venv/bin/pip install -q -r /home/$u/moayeyak/requirements.txt; done'

# ---- PG: 세 서버와 같은 공통 설정 + 개발 DB(2025-05-12 운영 사본)
conf_d=$(ls -d "$ROOT"/etc/postgresql/*/main/conf.d | head -1)
install -m 0644 "$B/base/postgresql/50-logging.conf" "$B/base/postgresql/50-listen.conf" "$conf_d/"
hba="${conf_d%/conf.d}/pg_hba.conf"; line="host    all             all             10.0.0.0/16             scram-sha-256"
grep -qxF "$line" "$hba" || echo "$line" >> "$hba"
"${NS[@]}" chown -R postgres:postgres "${conf_d#$ROOT}"
install -d "$ROOT/root/.c"; cp "$B/carryover/make_carryover.py" "$ROOT/root/.c/"
"${NSP[@]}" bash -c "set -e; pg_ctlcluster 16 main start
  python3 -I /root/.c/make_carryover.py --dump-at 2025-05-12 --dump-out /home/seoyeon/moayeyak-20250512.sql.gz --keep-db moayeyak_dev
  runuser -u postgres -- psql -qX -c \"ALTER ROLE moayeyak LOGIN PASSWORD '$PW';\" >/dev/null
  pg_ctlcluster 16 main stop; chown seoyeon:seoyeon /home/seoyeon/moayeyak-20250512.sql.gz"
rm -rf "$ROOT/root/.c"

# ---- 다른 서버로 이어지는 흔적: known_hosts(해시) — 덤프는 db-backup-01에서, 배포는 stg-01·web-01로
kh() {  # kh <파일> <주소> <이름> <키 파일>…
  local f=$1; shift
  while [ $# -ge 3 ]; do printf '%s,%s %s\n' "$2" "$1" "$(awk '{print $1, $2}' "$3")"; shift 3; done > "$f.plain"
  ssh-keygen -H -f "$f.plain" >/dev/null 2>&1; mv "$f.plain" "$f"; rm -f "$f.plain.old"
}
for u in jihoon seoyeon; do install -d -m 0700 "$ROOT/home/$u/.ssh"; done
kh "$ROOT/home/jihoon/.ssh/known_hosts" web-01 "$WEB_IP" "$WEB_KEY" db-backup-01 "$DBB_IP" "$DBB_KEY" "$STG" "$STG_IP" "$STG_KEY"
kh "$ROOT/home/seoyeon/.ssh/known_hosts" "$STG" "$STG_IP" "$STG_KEY" db-backup-01 "$DBB_IP" "$DBB_KEY" web-01 "$WEB_IP" "$WEB_KEY"
for h in "$STG_IP $STG" "$WEB_IP web-01" "$DBB_IP db-backup-01"; do grep -q " ${h#* }$" "$ROOT/etc/hosts" || echo "$h" >> "$ROOT/etc/hosts"; done

# ---- 히스토리: 저장소 만들기(박지훈, 구축일) → 개발·배포 → 마지막 날(이서연: 덤프 복원, staging push)
cat > "$ROOT/home/jihoon/.bash_history" <<'EOF'
sudo -u postgres createuser moayeyak
sudo -u postgres createdb -O moayeyak moayeyak_dev
cd moayeyak
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
vi .env
.venv/bin/flask --app wsgi run --debug --host 0.0.0.0
git remote -v
git push origin main
git log --oneline -5
git pull
.venv/bin/flask --app wsgi run --debug --host 0.0.0.0
git push staging main
git push production main
psql -h localhost -U moayeyak moayeyak_dev
git pull
git push staging main
git push production main
exit
EOF
cat > "$ROOT/home/seoyeon/.bash_history" <<'EOF'
git clone /srv/git/moayeyak.git
cd moayeyak
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
vi .env
.venv/bin/flask --app wsgi run --debug --host 0.0.0.0
git checkout -b admin-next
git commit -am "로그인 후 이동 경로를 /admin 아래로 제한"
git checkout main && git merge admin-next
git push origin main
git push staging main
git pull
.venv/bin/pip install -r requirements.txt
git push staging main
git push production main
scp ubuntu@db-backup-01:/backup/dumps/moayeyak-20250512.sql.gz ~/
sudo -u postgres dropdb moayeyak_dev
sudo -u postgres createdb -O moayeyak moayeyak_dev
gunzip -c ~/moayeyak-20250512.sql.gz | sudo -u postgres psql -q moayeyak_dev
git pull
.venv/bin/pip install -r requirements.txt
.venv/bin/flask --app wsgi run --debug --host 0.0.0.0
git push origin main
git push staging main
exit
EOF
"${NS[@]}" bash -c 'for u in jihoon seoyeon; do chown -R $u:$u /home/$u; chmod 600 /home/$u/.bash_history; done'

# ---- 시각: 구축·마지막 사용에 맞춘다(재구축 때 rsync -a로 옮김 → mtime 보존, ctime은 재구축일)
for u in jihoon seoyeon; do
  H=$ROOT/home/$u
  stamp "$BUILT" "$H/.bashrc" "$H/.profile" "$H/.bash_logout"
  find "$H/moayeyak/.venv" -exec touch -h -d "2025-05-12 11:52:30" {} +
  find "$H/moayeyak" -path "$H/moayeyak/.venv" -prune -o -exec touch -h -d "2025-05-12 11:49:15" {} +
  stamp "2024-09-02 11:03:28" "$H/.gitconfig"
done
stamp "2024-09-02 10:58:12" "$ROOT/home/jihoon/moayeyak/.env"
stamp "2024-09-23 09:12:40" "$ROOT/home/seoyeon/moayeyak/.env"
stamp "2025-05-08 17:41:03" "$ROOT/home/jihoon/.bash_history" "$ROOT/home/jihoon/.ssh/known_hosts" "$ROOT/home/jihoon/.ssh" "$ROOT/home/jihoon"
stamp "2025-05-12 13:21:07" "$ROOT/home/seoyeon/.ssh/known_hosts" "$ROOT/home/seoyeon/.ssh"
stamp "2025-05-12 13:24:52" "$ROOT/home/seoyeon/moayeyak-20250512.sql.gz"
stamp "$LAST" "$ROOT/home/seoyeon/.bash_history" "$ROOT/home/seoyeon"
find "$ROOT/srv/git" -exec touch -h -d "2025-05-12 13:58:29" {} +
echo "$NAME role ok(서비스 확인은 guest.sh online 뒤)"
