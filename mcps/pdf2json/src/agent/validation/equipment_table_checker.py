"""工艺设备表 tag 校验模块。

假设用户提供了工艺设备表（PDF），校验提取到的所有设备节点的 tag 是否在工艺设备表中。
若不在，说明模型可能将设备 tag 识别错了，生成警告供前端审核时高亮该节点。

前端警告解析约定（见 static/topology_viewer.html parseWarnings）：
  - warnings 为字符串列表
  - 通过正则 /'([^']+)'/ 提取第一个单引号包裹的内容作为 nodeId，用于高亮节点
因此警告格式必须为："...设备 '{node_id}' ... '{tag}' ..."
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src._internal.document_loader import (
    EquipmentTableEntry,
    TAG_STRICT_RE,
    normalize_tag,
    normalize_tag_full,
)


@dataclass
class TagCheckResult:
    """单个设备节点 tag 校验结果。"""

    node_id: str
    tag: str
    matched: bool
    reason: str = ""


def check_equipment_tags(
    equipment_nodes: list[Any],
    equipment_table: list[EquipmentTableEntry],
) -> list[TagCheckResult]:
    """校验设备节点的 tag 是否在工艺设备表中。

    Args:
        equipment_nodes: 设备节点列表，每个节点为 dict 或 PFDEquipmentNode，
                         需包含 id 和 tag 字段
        equipment_table: 工艺设备表记录列表

    Returns:
        校验结果列表（仅包含未匹配的节点）
    """
    if not equipment_table:
        return []

    # 构建设备表的归一化索引：完整形式 + 基础形式
    table_full_set: set[str] = set()
    table_base_set: set[str] = set()
    for entry in equipment_table:
        table_full_set.add(normalize_tag_full(entry.tag))
        table_base_set.add(normalize_tag(entry.tag))

    results: list[TagCheckResult] = []
    for node in equipment_nodes:
        node_id = _get_field(node, "id", "")
        tag = _get_field(node, "tag", "")

        if not tag or not tag.strip():
            # tag 为空，跳过（模型已提示看不清时留空）
            continue

        tag = tag.strip()
        if not TAG_STRICT_RE.match(tag):
            # tag 不符合位号格式，可能是模型编造，记为警告
            results.append(TagCheckResult(
                node_id=node_id,
                tag=tag,
                matched=False,
                reason="tag_format_invalid",
            ))
            continue

        full = normalize_tag_full(tag)
        base = normalize_tag(tag)

        if full in table_full_set:
            continue  # 完整匹配
        if base in table_base_set:
            continue  # 基础形式匹配（后缀差异，视为同一设备系列）

        results.append(TagCheckResult(
            node_id=node_id,
            tag=tag,
            matched=False,
            reason="tag_not_in_table",
        ))

    return results


def build_tag_warnings(results: list[TagCheckResult]) -> list[str]:
    """将校验结果转换为前端可解析的警告字符串列表。

    警告格式约定：第一个单引号包裹的内容为 node_id，前端据此高亮节点。
    """
    warnings: list[str] = []
    for r in results:
        if r.reason == "tag_format_invalid":
            msg = (
                f"equipment: 设备 '{r.node_id}' 的 tag '{r.tag}' 不符合位号格式，"
                f"可能识别错误"
            )
        else:
            msg = (
                f"equipment: 设备 '{r.node_id}' 的位号 '{r.tag}' 不在工艺设备表中，"
                f"可能识别错误"
            )
        warnings.append(msg)
    return warnings


def _get_field(obj: Any, field_name: str, default: Any = "") -> Any:
    """从 dict 或对象中获取字段值。"""
    if isinstance(obj, dict):
        return obj.get(field_name, default)
    return getattr(obj, field_name, default)
