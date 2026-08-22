"""Shared base types for assembly drawing extraction models."""

from __future__ import annotations

from enum import Enum
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

T = TypeVar("T")


class AssemblyDrawingType(str, Enum):
    """设备装配图分类：用于路由到对应的装配提取专家。"""

    COLUMN_TRAY = "column_tray"
    COLUMN_PACKED = "column_packed"
    REACTOR = "reactor"
    UNKNOWN = "unknown"


class NozzleRole(str, Enum):
    """Unified role classification for nozzles across all equipment types."""

    FEED = "feed"
    DRAW = "draw"
    REFLUX = "reflux"
    VAPOR_INLET = "vapor_inlet"
    BOTTOM_OUTLET = "bottom_outlet"
    MATERIAL_INLET = "material_inlet"
    MATERIAL_OUTLET = "material_outlet"
    UTILITY_INLET = "utility_inlet"
    UTILITY_OUTLET = "utility_outlet"
    UTILITY = "utility"
    VENT = "vent"
    DRAIN = "drain"
    MANWAY = "manway"
    INSTRUMENT = "instrument"
    OTHER = "other"
    UNKNOWN = "unknown"


class ClassifiedValue(BaseModel, Generic[T]):
    """Typed classified value with evidence and confidence."""

    model_config = ConfigDict(frozen=False)

    value: T
    evidence: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Quantity(BaseModel):
    """Numeric value with unit and original drawing text."""

    model_config = ConfigDict(frozen=False)

    value: Optional[float] = None
    unit: str = ""
    raw_text: str = ""

    @field_validator("value", mode="before")
    @classmethod
    def _coerce_value(cls, v: Any) -> Optional[float]:
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        text = str(v).strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None


class PositionalQuantity(BaseModel):
    """Quantity that may differ by position (top/bottom/side) in a column.

    Used for working_pressure / working_temperature where the drawing often
    shows separate values for 塔顶 / 塔底 / 塔侧, e.g.
    "0.03(顶)/0.05(底) MPaG" or "65(顶)/105(底) ℃".
    """

    model_config = ConfigDict(frozen=False)

    top: Optional[Quantity] = None
    bottom: Optional[Quantity] = None
    side: Optional[Quantity] = None
    raw_text: str = ""

    @model_validator(mode="before")
    @classmethod
    def _migrate_quantity_format(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "top" in data or "bottom" in data or "side" in data:
            return data
        if "value" in data or "unit" in data:
            value = data.get("value")
            unit = data.get("unit", "")
            raw_text = data.get("raw_text", "")
            return {
                "top": None,
                "bottom": {"value": value, "unit": unit, "raw_text": raw_text} if value is not None else None,
                "side": None,
                "raw_text": raw_text,
            }
        return data


class DrawingMetaInfo(BaseModel):
    """Title-block metadata shared across all assembly drawings."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    equipment_tag: str = ""
    equipment_name: str = ""
    drawing_name: str = ""


class NozzleBase(BaseModel):
    """Common nozzle fields shared across all assembly drawings."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    nozzle_id: str = ""
    service_description: str = ""
    nominal_size: str = ""
    flange_standard: str = ""
    face_type: str = ""
    pipe_size: str = ""
    evidence: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class AssemblyDrawingResult(BaseModel):
    """Base fields shared by all assembly drawing extraction results."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    source_image_id: str = ""
    info: DrawingMetaInfo = Field(default_factory=DrawingMetaInfo)
    warnings: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict
        return model_to_dict(self)


def _coerce_optional_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip()
    if not text:
        return None
    normalized = (
        text.replace("#", "")
        .replace("＃", "")
        .replace("号", "")
        .replace("块", "")
        .replace(",", "")
        .strip()
    )
    try:
        number = float(normalized)
    except ValueError:
        return None
    return int(number) if number.is_integer() else None
