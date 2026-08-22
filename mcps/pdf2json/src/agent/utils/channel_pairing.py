"""Channel-aware port pairing utilities for downstream topology inference."""
from __future__ import annotations

from typing import Optional

from src.core.models.unit.edges import Port
from src.core.models.unit.nodes import PFDEquipmentNode


def find_paired_output_port(node: PFDEquipmentNode, input_port_id: str) -> Optional[Port]:
    """根据 channel 配对规则，查找 input_port_id 对应的 output 端口。

    规则：
    - 找到 input_port 的 channel
    - 若 channel 为空 → 返回 None（无法配对）
    - 否则在同节点的 ports 中查找同 channel 的 output 端口
    - 若同 channel 有多个 output（如 separator），返回第一个
    - 若同 channel 仅 input 而无 output，返回 None
    """
    input_port = next((p for p in node.ports if p.id == input_port_id), None)
    if input_port is None:
        return None

    channel = (input_port.channel or "").strip()
    if not channel:
        return None

    for p in node.ports:
        if p.id == input_port_id:
            continue
        if (p.channel or "").strip() != channel:
            continue
        direction_val = getattr(getattr(p, "direction", ""), "value", getattr(p, "direction", ""))
        if str(direction_val) == "output":
            return p
    return None
