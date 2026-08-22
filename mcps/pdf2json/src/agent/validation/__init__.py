"""工艺设备表 tag 后校验模块。

校验提取到的设备节点 tag 是否在用户提供的工艺设备表中，
若不在则生成警告，前端审核时高亮对应节点。
"""

from .equipment_table_checker import (
    EquipmentTableEntry,
    TagCheckResult,
    build_tag_warnings,
    check_equipment_tags,
    normalize_tag,
    normalize_tag_full,
)

__all__ = [
    "EquipmentTableEntry",
    "TagCheckResult",
    "build_tag_warnings",
    "check_equipment_tags",
    "normalize_tag",
    "normalize_tag_full",
]
