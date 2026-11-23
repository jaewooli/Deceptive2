# 로컬 팜(WSL2) 복구 안내 — 네트워크·iptables가 꼬였을 때

로컬에서는 WSL2 자체가 팜이다(AWS metal 팜과 같은 구조: 한 OS가 KVM 하이퍼바이저 + 터널·라우팅). 팜 설정이 WSL2에 걸리므로,
문제가 생기면 아래 순서로 되돌린다. **위에서부터 시도하고, 안 되면 다음 단계로.** 어느 단계든 Windows는 영향을 받지 않는다.

## 0. 약속(설계 규칙) — 그래서 복구가 쉽다
- **부팅 때 자동으로 켜지는 것이 없다.** 팜은 `infra/local-vm/farm-host.sh up`으로만 켜진다(systemd 유닛 enable 안 함, `/etc/sysctl.d`에 안 씀).
  → **`wsl --shutdown` 한 번이면 커널 상태(규칙·경로·터널·sysctl·모듈)가 전부 원래대로.**
- 팜이 만드는 것은 이름으로 구별된다: 인터페이스 `relay`, `edh<번호>`, `ve-<이름>` / 경로표 `110~` `120` `141~` `191~` / 정책 규칙 pref `49~63` `161~` /
  nft 테이블 `edh_<번호>` `guest_build` `local_fwd` / iptables mangle의 `TTL --ttl-inc 1` 규칙 / Docker 쓸 때 `DOCKER-USER`의 relay·ve-·edh 허용 줄
- WSL2 자신의 `eth0`, 기본 경로, `local`·`main`·`default` 규칙(pref 0·32766·32767)은 **절대 건드리지 않는다**(검사가 확인 — `infra/checks/paths.local.txt`)

## 1. 기준선(11/23, 팜 올리기 전 WSL2 상태)
```
ip_forward = 0   rp_filter(all) = 2   arp_ignore(all) = 0   proxy_arp(all) = 0
ip rule:  0: from all lookup local / 32766: lookup main / 32767: lookup default
ip route: default via 172.25.48.1 dev eth0 (주소는 WSL 재시작 때 바뀔 수 있음)
인터페이스: lo, eth0 뿐 / Docker: 설치됨, 꺼짐 / /etc/wireguard 없음
```
iptables·nft 기준선은 팜을 올릴 때(팜 인터페이스가 하나도 없을 때) `out/local-farm/baseline-<시각>.txt`에 자동 저장, 내릴 때 `after-down-<시각>.txt` — `diff`로 남은 것 확인.

**11/23 처음 올릴 때 WSL2에 한 일**: 패키지 설치 `wireguard-tools iptables systemd-container nftables`(nftables는 "설정만 남은 제거" 상태였음 —
다시 설치하고 **부팅 서비스는 꺼 둠**: 켜지면 부팅 때 `/etc/nftables.conf`로 규칙을 전부 비워 Docker 규칙까지 지운다), 커널 모듈 `nbd wireguard tun xt_HL`(재부팅하면 사라짐).
지운 것 없음. 패키지를 되돌리려면 `sudo apt-get remove wireguard-tools iptables systemd-container nftables`(데이터와 무관).

## 2. 증상 → 먼저 볼 것
| 증상 | 확인 명령 | 정상 |
|---|---|---|
| WSL2에서 인터넷이 안 됨 | `ip route get 1.1.1.1` / `ip rule` | `dev eth0`, 규칙 3개 + 팜 규칙(pref 49~) — pref 0이 사라졌거나 main보다 앞에 낯선 규칙이 있으면 원인 |
| 랩 VM에 ssh 안 됨(127.0.0.1:22xx) | `ss -ltnp \| grep 22` / `pgrep -a qemu` | QEMU가 떠 있고 포트가 열림(QEMU 사용자망은 iptables와 무관) |
| VM끼리는 되는데 디코이로만 안 감 | `infra/local-vm/farm-host.sh check` (경로 단언) | 전부 ✓ |
| Docker 컨테이너 네트워크 이상 | `sudo iptables -S DOCKER-USER` | 팜이 넣은 줄은 `-i relay`·`-i ve-+`·`-i edh+`·`-o …` 허용뿐 |

## 3. 되돌리기 — 단계별
**1단계: 정리 스크립트(팜이 만든 것만 지움)**
```
infra/local-vm/farm-host.sh down     # 디코이 VM 정지 → 터널·규칙·경로·nft·TTL 규칙 제거 → sysctl을 기준선 값으로
```

**2단계: 손으로 하나씩(정리 스크립트가 실패했을 때)**
```
# 디코이 VM·트랩 컨테이너
for u in $(systemctl list-units --no-legend --plain 'guest@*' 'systemd-nspawn@trap-*' 'wg-quick@*' | awk '{print $1}'); do sudo systemctl stop $u; done
# 디스크 마운트
 sudo umount -R /var/lib/machines/* 2>/dev/null; for d in /dev/nbd*; do sudo qemu-nbd -d $d >/dev/null 2>&1; done
# 터널·디코이 인터페이스
for i in relay $(ip -o link | awk -F': ' '{print $2}' | grep -E '^(edh[0-9]+|ve-)' | cut -d@ -f1); do sudo ip link del "$i"; done
# 정책 규칙(팜 것만: pref 49~63, 161~199)
ip rule | awk -F: '$1>=49 && $1<=63 || $1>=161 && $1<=199 {print $1}' | while read p; do sudo ip rule del pref "$p"; done
# 경로표
for t in 110 111 112 113 120 141 142 191 192; do sudo ip route flush table $t; done
# nft 테이블
for t in guest_build local_fwd edh_1 edh_2; do sudo nft delete table ip $t 2>/dev/null; done
# iptables TTL 규칙(mangle) — 목록을 보고 같은 줄을 -A → -D로
sudo iptables -t mangle -S | grep TTL          # 예) sudo iptables -t mangle -D PREROUTING -i relay -j TTL --ttl-inc 1
# sysctl 기준선으로
sudo sysctl -w net.ipv4.ip_forward=0 net.ipv4.conf.all.arp_ignore=0 net.ipv4.conf.all.rp_filter=2
```

**3단계: WSL 재시작(가장 확실 — 0의 약속 덕분에 전부 원래대로)**
Windows PowerShell에서:
```
wsl --shutdown
```
그다음 WSL 터미널을 다시 열면 된다. 랩 VM은 꺼지므로 `infra/local-vm/lab.sh up all`로 다시 켠다(디스크는 그대로).

**4단계: 그래도 이상하면(파일이 남은 경우)**
팜이 쓰는 파일 위치 — 지워도 되는 것들:
```
/etc/wireguard/relay.* /etc/wireguard/edh*.*      # 터널 키·설정(지우면 터널 키가 바뀜 → 센서·EDH를 다시 설치해야 함)
/etc/guest/ /var/lib/guests/ /var/log/guests/      # 디코이 VM 정의·디스크(디스크를 지우면 디코이를 다시 만들어야 함)
/etc/systemd/system/guest@.service /usr/local/lib/relay/
```
지운 뒤 `wsl --shutdown`.

## 4. 연락이 안 될 때 나에게(Claude) 줄 정보
```
ip -br link; ip rule; ip route; ip route show table all | grep -v '^local' | head -40
sudo iptables -S; sudo iptables -t mangle -S; sudo iptables -t nat -S; sudo nft list tables
sysctl net.ipv4.ip_forward net.ipv4.conf.all.rp_filter net.ipv4.conf.all.arp_ignore
```
