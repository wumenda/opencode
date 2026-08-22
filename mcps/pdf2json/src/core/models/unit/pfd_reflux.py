"""PFD 塔与反应器回流结构分析数据模型。

对应 ``pfd_reflux`` 工作流的输出结构，从 PFD 图纸图片中提取：
    - 所有塔（``towers``）：位号、回流结构判断、回流详情（冷凝器/再沸器/回流量）、
      塔自身操作条件（塔顶/塔釜温度压力）。
    - 所有反应器（``reactors``）：位号、回流/循环结构判断、反应器自身操作条件
      （温度、压力）。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class Quantity(BaseModel):
    """带单位的物理量，用于温度、压力、流量等。

    Fields:
        value: 数值。无法识别时留 None。
        unit: 单位字符串（如 "℃"、"MPa"、"kg/h"）。
    """

    model_config = ConfigDict(frozen=False)

    value: Optional[float] = None
    unit: str = ""

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict

        return model_to_dict(self)


class RefluxStructure(BaseModel):
    """回流结构判断结果。

    用于判断塔/反应器是否存在回流结构：
    塔顶物料流出后又回到该塔自身（塔顶回流），
    或塔釜物料流出后又回到该塔自身（塔釜回流）。

    Fields:
        has_reflux: 是否存在回流结构。
        reflux_type: 回流类型，取值：
            "top"（仅塔顶回流）、"bottom"（仅塔釜回流）、
            "top_and_bottom"（塔顶与塔釜均有回流）、"none"（无回流）。
        description: 回流结构的文字描述（如管线路径、回流位置）。
    """

    model_config = ConfigDict(frozen=False)

    has_reflux: bool = False
    reflux_type: str = "none"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict

        return model_to_dict(self)


class TowerRefluxDetail(BaseModel):
    """塔回流详情。

    仅当塔存在回流结构（``reflux_structure.has_reflux=True``）时填写。

    Fields:
        has_top_condenser: 塔顶是否有冷凝器（一种换热器）。
            无法判断时填 None。
        has_bottom_reboiler: 塔釜是否有再沸器。
            无法判断时填 None。
        top_condenser_tag: 塔顶冷凝器的设备位号（如 "E-101"）。无则留空字符串。
        bottom_reboiler_tag: 塔釜再沸器的设备位号（如 "E-102"）。无则留空字符串。
        reflux_flow_rate: 回流管线的回流量（带单位）。
    """

    model_config = ConfigDict(frozen=False)

    has_top_condenser: Optional[bool] = None
    has_bottom_reboiler: Optional[bool] = None
    top_condenser_tag: str = ""
    bottom_reboiler_tag: str = ""
    reflux_flow_rate: Quantity = Field(default_factory=Quantity)

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict

        return model_to_dict(self)


class TowerOperatingConditions(BaseModel):
    """塔自身操作条件。

    Fields:
        top_temperature: 塔顶温度（带单位）。
        top_pressure: 塔顶压力（带单位）。
        bottom_temperature: 塔釜温度（带单位）。
        bottom_pressure: 塔釜压力（带单位）。
    """

    model_config = ConfigDict(frozen=False)

    top_temperature: Quantity = Field(default_factory=Quantity)
    top_pressure: Quantity = Field(default_factory=Quantity)
    bottom_temperature: Quantity = Field(default_factory=Quantity)
    bottom_pressure: Quantity = Field(default_factory=Quantity)

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict

        return model_to_dict(self)


class TowerInfo(BaseModel):
    """单个塔的完整信息。

    Fields:
        tag: 塔的设备位号（如 "T-101"、"C-201"）。
        name: 塔的名称（如 "脱甲烷塔"）。无则留空字符串。
        reflux_structure: 回流结构判断结果。
        reflux_detail: 回流详情（仅当 reflux_structure.has_reflux=True 时填写，
            否则为 None）。
        operating_conditions: 塔自身操作条件（塔顶/塔釜温度压力）。
    """

    model_config = ConfigDict(frozen=False)

    tag: str
    name: str = ""
    reflux_structure: RefluxStructure = Field(default_factory=RefluxStructure)
    reflux_detail: Optional[TowerRefluxDetail] = None
    operating_conditions: TowerOperatingConditions = Field(
        default_factory=TowerOperatingConditions
    )

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict

        return model_to_dict(self)


class ReactorOperatingConditions(BaseModel):
    """反应器自身操作条件。

    Fields:
        temperature: 反应器温度（带单位）。
        pressure: 反应器压力（带单位）。
    """

    model_config = ConfigDict(frozen=False)

    temperature: Quantity = Field(default_factory=Quantity)
    pressure: Quantity = Field(default_factory=Quantity)

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict

        return model_to_dict(self)


class ReactorInfo(BaseModel):
    """单个反应器的完整信息。

    Fields:
        tag: 反应器的设备位号（如 "R-101"）。
        name: 反应器的名称（如 "加氢反应器"）。无则留空字符串。
        reflux_structure: 回流/循环结构判断结果（反应器也可能存在循环回流结构）。
        operating_conditions: 反应器自身操作条件（温度、压力）。
    """

    model_config = ConfigDict(frozen=False)

    tag: str
    name: str = ""
    reflux_structure: RefluxStructure = Field(default_factory=RefluxStructure)
    operating_conditions: ReactorOperatingConditions = Field(
        default_factory=ReactorOperatingConditions
    )

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict

        return model_to_dict(self)


class PFDRefluxAnalysis(BaseModel):
    """PFD 塔与反应器回流结构分析结果，对应一份图纸图片。

    Fields:
        towers: 塔信息列表。
        reactors: 反应器信息列表。
        warnings: 抽取过程中的告警信息。
    """

    model_config = ConfigDict(frozen=False)

    towers: list[TowerInfo] = Field(default_factory=list)
    reactors: list[ReactorInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict

        return model_to_dict(self)
