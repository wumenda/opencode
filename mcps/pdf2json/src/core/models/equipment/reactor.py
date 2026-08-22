"""Reactor domain models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common import AssemblyDrawingResult, ClassifiedValue, NozzleBase, NozzleRole, Quantity


class ReactorType(str, Enum):
    """Supported reactor types."""

    FIXED_TUBE = "fixed_tube"
    FLOATING_HEAD = "floating_head"
    U_TUBE = "u_tube"
    UNKNOWN = "unknown"


class FlowPattern(str, Enum):
    """Flow pattern in the reactor."""

    COUNTERCURRENT = "countercurrent"
    COCURRENT = "cocurrent"
    CROSSFLOW = "crossflow"
    UNKNOWN = "unknown"


class MaterialFlowDirection(str, Enum):
    """Material flow direction for shell-side or tube-side."""

    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    UNKNOWN = "unknown"


class InletOutletQuantity(BaseModel):
    """Temperature pair with inlet and outlet for one medium/phase."""

    model_config = ConfigDict(frozen=False)

    inlet: Quantity = Field(default_factory=Quantity)
    outlet: Quantity = Field(default_factory=Quantity)

    @model_validator(mode="before")
    @classmethod
    def _migrate_from_separate_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "inlet" in data or "outlet" in data:
            return data
        return {"inlet": data, "outlet": Quantity().model_dump()}


class ReactorSideData(BaseModel):
    """Shell-side or tube-side operating data for a reactor."""

    model_config = ConfigDict(frozen=False)

    type: str = ""
    medium: list[str] = Field(default_factory=list)

    @field_validator("medium", mode="before")
    @classmethod
    def _coerce_medium(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str):
            if not value.strip():
                return []
            parts = [p.strip() for p in value.replace("、", "/").replace("，", "/").replace(",", "/").split("/") if p.strip()]
            return parts if parts else []
        if value is None:
            return []
        return [str(value).strip()]

    flow_direction: ClassifiedValue[MaterialFlowDirection] = Field(
        default_factory=lambda: ClassifiedValue(value=MaterialFlowDirection.UNKNOWN)
    )
    density: dict[str, Quantity] = Field(default_factory=lambda: {"default": Quantity()})
    working_temperature: dict[str, InletOutletQuantity] = Field(
        default_factory=lambda: {"default": InletOutletQuantity()}
    )

    @field_validator("flow_direction", mode="before")
    @classmethod
    def _coerce_flow_direction(cls, value: Any) -> ClassifiedValue[MaterialFlowDirection]:
        if isinstance(value, ClassifiedValue):
            return value
        if isinstance(value, dict):
            v = value.get("value", "")
            if v is None or (isinstance(v, str) and not v.strip()):
                return ClassifiedValue(value=MaterialFlowDirection.UNKNOWN)
            if isinstance(v, str):
                normalized = v.strip().lower()
                for member in MaterialFlowDirection:
                    if member.value == normalized:
                        return ClassifiedValue(
                            value=member,
                            evidence=value.get("evidence", ""),
                            confidence=value.get("confidence", 0.0),
                        )
            return ClassifiedValue(value=MaterialFlowDirection.UNKNOWN)
        if isinstance(value, str):
            if not value.strip():
                return ClassifiedValue(value=MaterialFlowDirection.UNKNOWN)
            normalized = value.strip().lower()
            for member in MaterialFlowDirection:
                if member.value == normalized:
                    return ClassifiedValue(value=member)
        return ClassifiedValue(value=MaterialFlowDirection.UNKNOWN)

    @field_validator("density", mode="before")
    @classmethod
    def _normalize_dict_quantity(cls, value: Any) -> dict[str, Any]:
        if value is None or not isinstance(value, dict):
            return {"default": {"value": None, "unit": ""}}
        result: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str) or not k.strip():
                continue
            if isinstance(v, dict):
                result[k] = v
            elif isinstance(v, (int, float)) or v is None:
                result[k] = {"value": v, "unit": ""}
        if not result:
            return {"default": {"value": None, "unit": ""}}
        return result

    @field_validator("working_temperature", mode="before")
    @classmethod
    def _normalize_working_temperature(cls, value: Any) -> dict[str, Any]:
        if value is None or not isinstance(value, dict):
            return {"default": {"inlet": {"value": None, "unit": ""}, "outlet": {"value": None, "unit": ""}}}
        result: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str) or not k.strip():
                continue
            if isinstance(v, dict):
                if "inlet" in v or "outlet" in v:
                    result[k] = v
                else:
                    result[k] = {"inlet": v, "outlet": {"value": None, "unit": ""}}
            elif isinstance(v, (int, float)) or v is None:
                result[k] = {"inlet": {"value": v, "unit": ""}, "outlet": {"value": None, "unit": ""}}
        if not result:
            return {"default": {"inlet": {"value": None, "unit": ""}, "outlet": {"value": None, "unit": ""}}}
        return result

    @model_validator(mode="before")
    @classmethod
    def _migrate_inlet_outlet_temperature(cls, data: Any) -> Any:
        """Migrate legacy inlet_temperature/outlet_temperature to working_temperature."""
        if not isinstance(data, dict):
            return data
        if "working_temperature" in data:
            return data
        inlet_temp = data.pop("inlet_temperature", None)
        outlet_temp = data.pop("outlet_temperature", None)
        if inlet_temp is None and outlet_temp is None:
            return data
        wt: dict[str, Any] = {}
        all_keys: set[str] = set()
        if isinstance(inlet_temp, dict):
            all_keys.update(inlet_temp.keys())
        if isinstance(outlet_temp, dict):
            all_keys.update(outlet_temp.keys())
        if not all_keys:
            all_keys = {"default"}
        for key in all_keys:
            inlet_val = (inlet_temp or {}).get(key, {"value": None, "unit": ""}) if isinstance(inlet_temp, dict) else {"value": None, "unit": ""}
            outlet_val = (outlet_temp or {}).get(key, {"value": None, "unit": ""}) if isinstance(outlet_temp, dict) else {"value": None, "unit": ""}
            wt[key] = {"inlet": inlet_val, "outlet": outlet_val}
        data["working_temperature"] = wt
        return data


class ReactorNozzle(NozzleBase):
    """Nozzle information extracted from the nozzle table on the drawing.

    Uses the unified NozzleRole enum from common.py (shared with ColumnNozzle).
    """

    nozzle_role: NozzleRole = NozzleRole.UNKNOWN
    elevation: Quantity = Field(default_factory=Quantity)

    @field_validator("nozzle_role", mode="before")
    @classmethod
    def _coerce_nozzle_role(cls, value: Any) -> NozzleRole:
        if value is None or (isinstance(value, str) and not value.strip()):
            return NozzleRole.UNKNOWN
        if isinstance(value, str):
            normalized = value.strip().lower()
            for member in NozzleRole:
                if member.value == normalized:
                    return member
        return NozzleRole.UNKNOWN


class Reactor(AssemblyDrawingResult):
    """Structured extraction result for one reactor assembly drawing page."""

    reactor_type: ReactorType = ReactorType.UNKNOWN
    flow_pattern: ClassifiedValue[FlowPattern] = Field(
        default_factory=lambda: ClassifiedValue(value=FlowPattern.UNKNOWN)
    )
    design_pressure: Quantity = Field(default_factory=Quantity)
    design_temperature: Quantity = Field(default_factory=Quantity)
    shell_side: ReactorSideData = Field(default_factory=ReactorSideData)
    tube_side: ReactorSideData = Field(default_factory=ReactorSideData)
    nozzles: list[ReactorNozzle] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_working_fields(cls, data: Any) -> Any:
        """Remove legacy working_pressure/working_temperature from top level."""
        if not isinstance(data, dict):
            return data
        data.pop("working_pressure", None)
        data.pop("working_temperature", None)
        return data

    @field_validator("reactor_type", mode="before")
    @classmethod
    def _coerce_reactor_type(cls, value: Any) -> ReactorType:
        if value is None or (isinstance(value, str) and not value.strip()):
            return ReactorType.UNKNOWN
        if isinstance(value, str):
            normalized = value.strip().lower()
            for member in ReactorType:
                if member.value == normalized:
                    return member
        return ReactorType.UNKNOWN

    @field_validator("flow_pattern", mode="before")
    @classmethod
    def _coerce_flow_pattern(cls, value: Any) -> ClassifiedValue[FlowPattern]:
        if isinstance(value, ClassifiedValue):
            return value
        if isinstance(value, dict):
            v = value.get("value", "")
            if v is None or (isinstance(v, str) and not v.strip()):
                return ClassifiedValue(value=FlowPattern.UNKNOWN)
            if isinstance(v, str):
                normalized = v.strip().lower()
                for member in FlowPattern:
                    if member.value == normalized:
                        return ClassifiedValue(
                            value=member,
                            evidence=value.get("evidence", ""),
                            confidence=value.get("confidence", 0.0),
                        )
            return ClassifiedValue(value=FlowPattern.UNKNOWN)
        if isinstance(value, str):
            if not value.strip():
                return ClassifiedValue(value=FlowPattern.UNKNOWN)
            normalized = value.strip().lower()
            for member in FlowPattern:
                if member.value == normalized:
                    return ClassifiedValue(value=member)
        return ClassifiedValue(value=FlowPattern.UNKNOWN)
