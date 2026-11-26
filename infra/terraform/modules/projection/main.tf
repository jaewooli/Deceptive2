# 투영 ENI — 투영 디코이 하나 = 센서의 ENI 하나(Acalvio 투영의 센서 쪽, HANDOFF 8·9절).
#
# 왜 ENI의 "주 IP"가 투영 주소인가:
#   VPC엔 L2가 없어 ARP로 주소를 가로챌 수 없다. VPC는 어떤 주소로 온 패킷을 "그 주소를 가진 ENI"에만 넘긴다(HANDOFF 8절).
#   그래서 투영 주소는 AWS 쪽에서 센서 ENI의 주소여야 한다. 센서 OS는 이 NIC에서 주소를 받지 않고(dhcp4: false, 169.254.31.1만 —
#   servers/hosts/sensor/install.sh nic()) 들어온 패킷을 정책 라우팅으로 WireGuard(relay)에 넘긴다 → 팜 디코이 VM.
#   응답은 출발지 = 투영 주소 = 이 ENI의 주소라 source/dest check를 통과한다(끌 필요 없음).
# 왜 디코이마다 ENI를 따로: 같은 ENI의 보조 IP로 여러 디코이를 두면 같은 MAC → 이웃의 ARP 캐시에서 "한 대"로 묶임(HANDOFF 9절).
#   팜 VM의 NIC MAC도 이 ENI MAC으로 맞춘다(engine.py place_projection이 센서에서 MAC을 읽어 VM에 줌).
# 주소는 엔진의 블렌딩(이웃 옆 주소)이 정한다 → 여기선 받기만(variables.tf projections, README "투영 주소 두 단계").

variable "project" {
  type = string
}

variable "instance_id" {
  description = "센서 인스턴스"
  type        = string
}

variable "subnet_ids" {
  description = "구간 이름 → 서브넷 ID (public·internal)"
  type        = map(string)
}

variable "security_group_id" {
  type = string
}

variable "projections" {
  type = map(object({
    segment      = string
    ip           = string
    device_index = number
  }))
}

resource "aws_network_interface" "this" {
  for_each        = var.projections
  subnet_id       = var.subnet_ids[each.value.segment]
  private_ips     = [each.value.ip]
  security_groups = [var.security_group_id]

  tags = { Name = "${var.project}-relay-${each.key}" }
}

resource "aws_network_interface_attachment" "this" {
  for_each             = var.projections
  instance_id          = var.instance_id
  network_interface_id = aws_network_interface.this[each.key].id
  device_index         = each.value.device_index
}

output "enis" {
  description = "디코이 이름 → 투영 ENI(aws.yml segments.<구간>.sensor_nics 에 OS NIC 이름으로 들어감)"
  value = { for k, p in var.projections : k => {
    segment      = p.segment
    ip           = p.ip
    eni_id       = aws_network_interface.this[k].id
    mac          = aws_network_interface.this[k].mac_address
    device_index = p.device_index
    # Nitro(t3)에서 device_index N → 보통 ens(5+N). 확정이 아니라 추정 — 첫날 센서에서 `ip -br link`로 MAC과 맞춰 확인(local-aws-parity 4절)
    ifname_guess = "ens${5 + p.device_index}"
  } }
}
