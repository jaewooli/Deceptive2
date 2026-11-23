# 로컬 ↔ AWS 대응 — 로컬 검증이 AWS에서 깨지지 않게 (11/23 사용자 결정)

목표: **로컬에서 통과한 것이 AWS에서도 통과한다.** 그러려고 로컬은 AWS 구조의 축소판으로 두고, 차이는 환경 프로필 한 곳에만 둔다.

## 1. 원칙
1. **같은 코드, 같은 순서.** 팜·센서·디코이·미끼 엔진·검사는 한 벌. 코드 안에 로컬 분기(`if local`)를 두지 않는다
2. **차이는 환경 프로필 하나(`infra/env/<환경>.yml`)에만.** 주소·MTU·터널 엔드포인트·하드웨어 모양·apt 프록시·부팅 자동 시작 여부. 값마다 왜 다른지 적는다
3. **로컬로 검증 못 하는 것은 목록으로**(4절) — AWS 첫날 검사 항목. "로컬에서 됐다"를 AWS 근거로 쓰지 않는다
4. **검사 기대값은 같은 환경의 진짜 서버에서 그때 잰다**(TTL·MTU·detect-virt·커널 등). 주소는 인벤토리·레지스트리에서 만든다 — 손으로 박은 값 금지
5. 로컬 팜(WSL2)은 사용자 작업 환경 — 부팅 자동 시작 없음, 팜이 만든 것만 지움(`docs/local-farm-recovery.md`)

## 2. 대응표
| 구성 | AWS | 로컬 | 코드 | 차이(프로필 값) |
|---|---|---|---|---|
| 팜 | 한 OS가 KVM + 터널·라우팅: metal **또는** 중첩 지원 인스턴스(C8i·M8i·R8i, 3절) | **WSL2 자체**(Ubuntu 24.04, KVM + 터널·라우팅) | 같음 | 커널(WSL2), 부팅 자동 시작 없음, Docker 공존 |
| 디코이 VM | 팜 위 KVM | WSL2 위 KVM(다른 랩 VM과 같은 단계) | 같음(guest.sh) | 하드웨어 모양: aws = EC2처럼, local = 랩 VM처럼 |
| 센서 | t3.small, 구간마다 ENI(보조 IP = 투영 주소) | VM, 구간마다 NIC(proxy ARP) | 같음 | NIC 이름·게이트웨이 |
| 터널 엔드포인트 | 팜 서브넷 주소 | 10.0.2.2(VM에서 본 WSL2) | 같음 | 주소 |
| 서브넷·라우터 | VPC(암묵적 라우터, TTL 안 줄임) | LAN 2개 + router VM(TTL 보정) | 로컬 전용 장치 | 로컬에만 |
| MTU | 9001 | 1500 | 같음(구간 MTU를 읽음) | 자동 |
| IMDS | 진짜 서버: AWS / 디코이: 팜이 흉내 | 없음 | 미구현 | AWS에서만 의미 |

## 3. 조사(11/23) — 로컬로 못 보는 것의 가장 가까운 근거
- **EC2 중첩 가상화**: 2026년 초부터 Intel 8세대(C8i·M8i·R8i)에서 공식 지원, KVM·Hyper-V를 L1으로 명시, 추가 요금 없음, 시작 때 CPU 옵션 `NestedVirtualization=enabled`. 성능 민감하면 여전히 metal 권장. 7세대 확대·리전은 2차 출처 → **서울 리전 제공 여부를 AWS 문서로 확인할 것**
  ([InfoQ](https://www.infoq.com/news/2026/03/aws-ec2-nested-virtualization/), [Techzine](https://www.techzine.eu/news/infrastructure/138831/aws-expands-ec2-with-support-for-nested-virtualization/), [AWS Builder](https://builder.aws.com/content/3F3SMtAj6AQCMtLl6hkoLaIVw7O/ditch-the-bare-metal-android-emulation-on-ec2-with-nested-virtualization))
- **detect-virt `amazon`**: systemd는 DMI 제조사 "Amazon EC2" → `amazon`, VM과 metal 구분은 SMBIOS BIOS 특성(가상 머신 비트) — QEMU `-smbios`로 어디까지 맞는지는 실험 필요
  ([systemd 패치](https://git.almalinux.org/rpms/systemd/src/branch/c8s/0848-virt-detect-Amazon-EC2-Nitro-instance.patch), [BIOS 특성 패치](https://git.centos.org/rpms/systemd/raw/28136447b1b4b19552145c094ba06228252cb4fe/f/SOURCES/0852-Use-BIOS-characteristics-to-distinguish-EC2-bare-met.patch), [man](https://man.archlinux.org/man/systemd-detect-virt.1.en))
- **IMDS 흉내**: AWS 공식 [amazon-ec2-metadata-mock](https://www.github.com/aws/amazon-ec2-metadata-mock/releases?page=3)(IMDSv1·v2), cloud-init에도 [mock-meta.py](https://sources.debian.org/src/cloud-init/25.3-2/tools/mock-meta.py). cloud-init Ec2 데이터소스는 플랫폼이 AWS로 판정돼야 IMDSv2(`latest/api/token`, `X-aws-ec2-metadata-token`)를 씀 → DMI 흉내와 묶임
  ([DataSourceEc2.py](https://sources.debian.org/src/cloud-init/25.3-2/cloudinit/sources/DataSourceEc2.py), [문서](https://docs.cloud-init.io/en/26.1/_sources/reference/datasources/ec2.rst.txt))
- **MTU 9001 위 WireGuard**: VPC 안은 9001, 바깥(IGW)은 1500, PMTUD는 보장 안 됨. WireGuard 바깥 UDP 단편화는 성능이 크게 떨어진다는 보고 — 디코이 트래픽은 적어 감수(터널 MTU를 낮추면 MSS 단서가 다시 생김, 11/23 학습 로그)
  ([AWS MTU](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-mtu.html), [AWS 블로그(MSS·PMTUD)](https://aws.amazon.com/ko/blogs/tech/aws-mtu-mss-pmtud/), [Cilium 이슈](https://github.com/cilium/cilium/issues/28413))

## 4. 로컬로 검증 못 하는 것 = AWS 첫날 검사
1. 팜 인스턴스(metal 또는 C8i 등 + 중첩)에서 디코이 VM 빌드·안정성·밀도
2. EC2 하드웨어 모양(detect-virt `amazon`, DMI, NVMe 디스크 이름·모델, NIC 이름·드라이버 `ena` — 드라이버는 못 맞출 수 있음 = 한계 후보)
3. IMDS 흉내 + Ec2 데이터소스(`cloud-id` = `aws`)
4. VPC가 ENI 보조 IP 패킷을 센서에 넘기는지, src/dst check, 보안 그룹
5. MTU 9001 단편화 경로, TTL(VPC 라우터)
6. 공격자 시점·경로·안쪽 검사 전체를 AWS 프로필로 재실행

## 5. 진행 순서
1. 환경 프로필 `infra/env/local.yml`(+ `aws.yml` 뼈대) → 흩어진 값 모으기, 정적 검사(코드에 로컬 주소 금지)
2. 검사 명세 생성형으로(주소 = 인벤토리·레지스트리, 기대값 = 진짜 서버 측정)
3. WSL2 팜 전환(`lab.sh farm-host up|down|check`, 기준선 저장, 정리 스크립트), farm VM 끔
4. 디코이 VM 배치(stg·dev) → 검사 3종
5. AWS 첫날 목록을 HANDOFF에 고정
