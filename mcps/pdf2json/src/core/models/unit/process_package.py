"""Process package paragraph extraction models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProcessPackageInfo(BaseModel):
    """从工艺包段落中提取的结构化信息。

    Fields:
        operation_description: 工序说明 — 该工序/单元的操作过程、工艺原理、
            操作条件等说明性文字。
        reaction_equation: 反应方程式 — 该工序中涉及的化学反应方程式。
            如有多个方程式，以换行符分隔；无则留空。
    """

    model_config = ConfigDict(frozen=False)

    operation_description: str = ""
    reaction_equation: str = ""
    warnings: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict

        return model_to_dict(self)
