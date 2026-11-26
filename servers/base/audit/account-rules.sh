#!/usr/bin/env bash
# 계정·서비스 자격증명 파일 감사 규칙을 이 서버의 계정과 서비스 유닛에서 만든다(서버마다 계정이 달라 고정 파일로 못 둠).
#   audit/account-rules.sh [루트] > /etc/audit/rules.d/61-account-files.rules
# 루트를 주면 그 아래 디스크(꺼진 서버)를 읽는다. 규칙 경로는 서버 안 경로
# - 로그인 셸 계정의 ~/.ssh·~/.aws 안 파일 열람        → key=secret-files
# - ~/.ssh 만들기, authorized_keys(2) 쓰기·속성 변경  → key=persistence
# - 서비스 유닛의 필수 EnvironmentFile(앞에 - 없는 것) 열람 → key=secret-files
# - 로그인 셸 계정의 홈이 70-user-files.rules의 고정 위치 밖이면 그 홈에서 로그인 세션이 만든·옮긴 파일 → key=user-file
# 계정·서비스가 바뀌면 다시 만든다(install.sh audit)
set -euo pipefail
R=${1:-}
echo "## 계정·서비스 자격증명 파일(account-rules.sh가 만듦)"
uf=()
while IFS=: read -r _ _ _ _ _ home shell; do
  case "$shell" in ""|*/nologin|*/false|*/sync) continue ;; esac
  [ "$home" != / ] && [ -d "$R$home" ] || continue
  for d in .ssh .aws; do
    [ -d "$R$home/$d" ] && echo "-a always,exit -F dir=$home/$d -F perm=r -F key=secret-files"
  done
  echo "-a always,exit -F path=$home/.ssh -F perm=wa -F key=persistence"
  if [ -d "$R$home/.ssh" ]; then
    for k in authorized_keys authorized_keys2; do echo "-a always,exit -F path=$home/.ssh/$k -F perm=wa -F key=persistence"; done
  fi
  case "$home" in /home|/home/*|/root|/root/*|/srv|/srv/*|/opt|/opt/*|/usr/local|/usr/local/*|/tmp|/tmp/*|/var/tmp|/var/tmp/*) ;;
    *) for a in b64 b32; do   # 70-user-files.rules와 같은 모양 — 파일 맨 뒤에(처음 맞는 규칙의 key만 남음: persistence·secret-files가 먼저)
         uf+=("-a always,exit -F arch=$a -S openat -F a2&0100 -F dir=$home -F auid!=unset -F success=1 -F key=user-file")
         uf+=("-a always,exit -F arch=$a -S open -F a1&0100 -F dir=$home -F auid!=unset -F success=1 -F key=user-file")
         uf+=("-a always,exit -F arch=$a -S creat,rename,renameat,renameat2 -F dir=$home -F auid!=unset -F success=1 -F key=user-file")
       done ;;
  esac
done < "$R/etc/passwd"
shopt -s nullglob
for u in "$R"/etc/systemd/system/*.service "$R"/usr/lib/systemd/system/*.service; do
  [ -f "$u" ] && [ ! -L "$u" ] || continue
  sed -n 's/^EnvironmentFile=\([^-].*\)$/\1/p' "$u"
done | sort -u | while read -r f; do
  case "$f" in /etc/default/*|/etc/environment) continue ;; esac
  [ -f "$R$f" ] && echo "-a always,exit -F path=$f -F perm=r -F key=secret-files"
done
[ ${#uf[@]} -eq 0 ] || printf '%s\n' "${uf[@]}"
exit 0
