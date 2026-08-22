"""Port count constraints for equipment nodes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .enums import EquipmentType


@dataclass(frozen=True)
class EquipmentPortConstraint:
    min_in: int
    max_in: int
    min_out: int
    max_out: int


EQUIPMENT_PORT_CONSTRAINTS: dict[EquipmentType, EquipmentPortConstraint] = {
    EquipmentType.PUMP: EquipmentPortConstraint(min_in=1, max_in=1, min_out=1, max_out=1),
    EquipmentType.COMPRESSOR: EquipmentPortConstraint(min_in=1, max_in=1, min_out=1, max_out=1),
    EquipmentType.HEAT_EXCHANGER: EquipmentPortConstraint(min_in=2, max_in=2, min_out=2, max_out=2),
    EquipmentType.REACTOR: EquipmentPortConstraint(min_in=1, max_in=3, min_out=1, max_out=3),
    EquipmentType.DISTILLATION_COLUMN: EquipmentPortConstraint(
        min_in=1, max_in=3, min_out=2, max_out=4
    ),
    EquipmentType.VESSEL: EquipmentPortConstraint(min_in=1, max_in=2, min_out=1, max_out=2),
    EquipmentType.TANK: EquipmentPortConstraint(min_in=1, max_in=1, min_out=1, max_out=1),
    EquipmentType.MIXER: EquipmentPortConstraint(min_in=2, max_in=4, min_out=1, max_out=1),
    EquipmentType.SEPARATOR: EquipmentPortConstraint(min_in=1, max_in=1, min_out=2, max_out=3),
    EquipmentType.FURNACE: EquipmentPortConstraint(min_in=1, max_in=2, min_out=1, max_out=2),
    EquipmentType.COOLER: EquipmentPortConstraint(min_in=1, max_in=2, min_out=1, max_out=2),
    EquipmentType.HEATER: EquipmentPortConstraint(min_in=1, max_in=2, min_out=1, max_out=2),
    EquipmentType.OTHER: EquipmentPortConstraint(min_in=0, max_in=4, min_out=0, max_out=4),
}


@dataclass
class EquipmentPortViolation:
    node_id: str
    equipment_type: str
    in_count: int
    out_count: int
    constraint: EquipmentPortConstraint
    violations: list[str]


@dataclass
class EquipmentChannelViolation:
    """通道（channel）配对违规：同 channel 端口未形成 input↔output 配对、或多端口设备未声明 channel。"""

    node_id: str
    equipment_type: str
    violations: list[str]


# 默认要求显式声明 channel 的设备类型（内部物料通道隔离，必须配对）
_CHANNEL_REQUIRED_EQUIPMENT_TYPES: set[EquipmentType] = {
    EquipmentType.HEAT_EXCHANGER,
    EquipmentType.COOLER,
    EquipmentType.HEATER,
}


# 多端口非混合设备应至少声明的 channel 数
_MIN_CHANNEL_COUNT: dict[EquipmentType, int] = {
    EquipmentType.HEAT_EXCHANGER: 2,
}


def get_equipment_port_constraint(key: EquipmentType | str) -> EquipmentPortConstraint | None:
    if isinstance(key, EquipmentType):
        return EQUIPMENT_PORT_CONSTRAINTS.get(key)
    try:
        eq_type = EquipmentType(key)
        return EQUIPMENT_PORT_CONSTRAINTS.get(eq_type)
    except ValueError:
        pass
    return None


def check_equipment_port_count(
    node: Any,
    fallback_in: int = 0,
    fallback_out: int = 0,
) -> EquipmentPortViolation | None:
    from .nodes import PFDEquipmentNode

    if not isinstance(node, PFDEquipmentNode):
        return None

    eq_type_raw = getattr(node, "equipment_type", None)
    if eq_type_raw is None:
        return None
    eq_type = eq_type_raw.value if hasattr(eq_type_raw, "value") else str(eq_type_raw)

    constraint = get_equipment_port_constraint(eq_type)
    if constraint is None:
        return None

    in_count = len(node.get_input_ports()) if hasattr(node, "get_input_ports") else fallback_in
    out_count = len(node.get_output_ports()) if hasattr(node, "get_output_ports") else fallback_out

    violations: list[str] = []
    if in_count < constraint.min_in:
        violations.append(f"输入端口过少({in_count} < {constraint.min_in})")
    if in_count > constraint.max_in:
        violations.append(f"输入端口过多({in_count} > {constraint.max_in})")
    if out_count < constraint.min_out:
        violations.append(f"输出端口过少({out_count} < {constraint.min_out})")
    if out_count > constraint.max_out:
        violations.append(f"输出端口过多({out_count} > {constraint.max_out})")

    if not violations:
        return None

    return EquipmentPortViolation(
        node_id=getattr(node, "id", "unknown"),
        equipment_type=eq_type,
        in_count=in_count,
        out_count=out_count,
        constraint=constraint,
        violations=violations,
    )


def check_equipment_channel(node: Any) -> EquipmentChannelViolation | None:
    """校验多端口设备的 channel（内部通道）配对一致性。

    规则：
    - 仅校验工艺端口（category != "utility"）。
    - 当端口总数 ≥ 2 时，要求声明 channel。
    - 同一 channel 至少应含 1 个 input 与 1 个 output（否则该 channel 无意义）。
    - 部分设备（_MIN_CHANNEL_COUNT）要求至少 N 个不同 channel。
    - HEAT_EXCHANGER / COOLER / HEATER 等必须给出非空 channel。
    """
    from .nodes import PFDEquipmentNode

    if not isinstance(node, PFDEquipmentNode):
        return None

    eq_type_raw = getattr(node, "equipment_type", None)
    if eq_type_raw is None:
        return None
    try:
        eq_type = (
            eq_type_raw if isinstance(eq_type_raw, EquipmentType) else EquipmentType(str(eq_type_raw))
        )
    except ValueError:
        return None

    process_ports = [
        p
        for p in getattr(node, "ports", []) or []
        if str(getattr(getattr(p, "category", ""), "value", getattr(p, "category", ""))) != "utility"
    ]

    if len(process_ports) < 2:
        return None

    violations: list[str] = []

    channel_groups: dict[str, dict[str, int]] = {}
    missing_channel = 0
    for p in process_ports:
        ch = (getattr(p, "channel", "") or "").strip()
        if not ch:
            missing_channel += 1
            continue
        direction_val = getattr(getattr(p, "direction", ""), "value", getattr(p, "direction", ""))
        bucket = channel_groups.setdefault(ch, {"input": 0, "output": 0, "unknown": 0})
        bucket[str(direction_val)] = bucket.get(str(direction_val), 0) + 1

    if eq_type in _CHANNEL_REQUIRED_EQUIPMENT_TYPES and missing_channel > 0:
        violations.append(f"{missing_channel} 个工艺端口未声明 channel")

    # 加热炉多盘管：process 端口 ≥ 4（≥2 组盘管）时必须声明 channel；单盘管不强制
    if eq_type == EquipmentType.FURNACE and len(process_ports) >= 4 and missing_channel > 0:
        violations.append(
            f"{missing_channel} 个工艺端口未声明 channel（多盘管加热炉必须声明 channel）"
        )

    min_required = _MIN_CHANNEL_COUNT.get(eq_type)
    if min_required and len(channel_groups) < min_required:
        violations.append(
            f"channel 数量不足：实际 {len(channel_groups)}，要求至少 {min_required}"
        )

    for ch, counts in channel_groups.items():
        if counts.get("input", 0) == 0 and counts.get("unknown", 0) == 0:
            violations.append(f"channel '{ch}' 无 input 端口")
        if counts.get("output", 0) == 0 and counts.get("unknown", 0) == 0:
            violations.append(f"channel '{ch}' 无 output 端口")

    # 混合器/分离器：所有 process 端口必须同一 channel（内部混合或分流）
    if eq_type in {EquipmentType.MIXER, EquipmentType.SEPARATOR}:
        process_channels = {
            (getattr(p, "channel", "") or "").strip()
            for p in process_ports
            if (getattr(p, "channel", "") or "").strip()
        }
        if len(process_channels) > 1:
            violations.append(
                f"{eq_type.value} 内部混合/分流，所有 process 端口应同一 channel，"
                f"实际声明了 {len(process_channels)} 个：{sorted(process_channels)}"
            )

    # 夹套/盘管启发式：reactor/vessel 同时含 process + utility 端口时，utility 必须 channel 隔离
    if eq_type in {EquipmentType.REACTOR, EquipmentType.VESSEL}:
        all_ports = getattr(node, "ports", []) or []
        has_process = any(
            str(getattr(getattr(p, "category", ""), "value", getattr(p, "category", ""))) == "process"
            for p in all_ports
        )
        has_utility = any(
            str(getattr(getattr(p, "category", ""), "value", getattr(p, "category", ""))) == "utility"
            for p in all_ports
        )
        if has_process and has_utility:
            utility_no_channel = sum(
                1
                for p in all_ports
                if str(getattr(getattr(p, "category", ""), "value", getattr(p, "category", ""))) == "utility"
                and not (getattr(p, "channel", "") or "").strip()
            )
            if utility_no_channel > 0:
                violations.append(
                    f"{utility_no_channel} 个 utility 端口未声明 channel（夹套/盘管必须与工艺通道隔离）"
                )

    if not violations:
        return None

    return EquipmentChannelViolation(
        node_id=getattr(node, "id", "unknown"),
        equipment_type=eq_type.value,
        violations=violations,
    )
