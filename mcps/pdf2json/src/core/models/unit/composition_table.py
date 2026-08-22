"""组分表（composition table）信息抽取数据模型。

对应 ``components.json`` 的数据结构，包含两部分：
    - ``components``：组分定义列表（名称 + 分子量）
    - ``streams``：物流列表，每个物流含流量、组成（摩尔/质量分数）、
      温度、压力、相态等信息。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class Component(BaseModel):
    """组分定义。

    Fields:
        name: 组分名称（如 "水"、"甲醇"、"TAME"）。
        molecular_weight: 分子量（g/mol）。无则留 None。
    """

    model_config = ConfigDict(frozen=False)

    name: str
    molecular_weight: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict

        return model_to_dict(self)


class Quantity(BaseModel):
    """带单位的物理量，用于流量、温度、压力等。

    Fields:
        value: 数值。无法识别时留 None。
        unit: 单位字符串（如 "kg/h"、"℃"、"MPa"）。
    """

    model_config = ConfigDict(frozen=False)

    value: Optional[float] = None
    unit: str = ""

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict

        return model_to_dict(self)


class CompositionEntry(BaseModel):
    """单个组分在某物流中的组成信息。

    Fields:
        component: 组分名称（与 ``Component.name`` 对应）。
        mole_fraction: 摩尔分数（0-1）。无则留 None。
        mass_fraction: 质量分数（0-1）。无则留 None。
    """

    model_config = ConfigDict(frozen=False)

    component: str
    mole_fraction: Optional[float] = None
    mass_fraction: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict

        return model_to_dict(self)


class Stream(BaseModel):
    """物流信息。

    Fields:
        stream_id: 物流编号（如 "1"、"2"、"S-101"）。
        flow_rate: 流量（带单位）。
        composition: 组成列表，每个元素对应一个组分的摩尔/质量分数。
        temperature: 温度（带单位）。
        pressure: 压力（带单位）。
        phase: 相态（如 "Liq"、"Vap"、"Li/Va"）。无则留空字符串。
    """

    model_config = ConfigDict(frozen=False)

    stream_id: str = ""
    flow_rate: Quantity = Field(default_factory=Quantity)
    composition: list[CompositionEntry] = Field(default_factory=list)
    temperature: Quantity = Field(default_factory=Quantity)
    pressure: Quantity = Field(default_factory=Quantity)
    phase: str = ""

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict

        return model_to_dict(self)


class CompositionTable(BaseModel):
    """组分表抽取结果，对应一份图片/PDF 页中的组分表。

    Fields:
        components: 组分定义列表。
        streams: 物流列表。
        warnings: 抽取过程中的告警信息。
    """

    model_config = ConfigDict(frozen=False)

    components: list[Component] = Field(default_factory=list)
    streams: list[Stream] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict

        return model_to_dict(self)
