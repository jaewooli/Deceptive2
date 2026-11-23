# 로컬 랩 전용 장치 검사(infra/checks/paths.py) — AWS에는 없는 것(VPC 라우터 흉내). AWS에선 돌리지 않는다
router | has | iptables -t mangle -S PREROUTING | -i enp0s3 -j TTL --ttl-inc 1 | 라우터: int → pub TTL 보정(VPC 라우터는 TTL을 안 줄임)
router | has | iptables -t mangle -S PREROUTING | -i enp0s8 -j TTL --ttl-inc 1 | 라우터: pub → int TTL 보정
router | has | sysctl -n net.ipv4.ip_forward | ^1$ | 라우터: 포워딩
