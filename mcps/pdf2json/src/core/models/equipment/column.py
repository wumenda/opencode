"""Column domain models."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common import AssemblyDrawingResult, NozzleBase, NozzleRole, PositionalQuantity, Quantity, _coerce_optional_int


class ColumnType(str, Enum):
    """Supported column internals."""

    TRAY = "tray"
    PACKED = "packed"
    UNKNOWN = "unknown"


class NumberingDirection(str, Enum):
    """Numbering direction of internal elements in the assembly drawing."""

    TOP_TO_BOTTOM = "top_to_bottom"
    BOTTOM_TO_TOP = "bottom_to_top"
    UNKNOWN = "unknown"


class DiameterSection(BaseModel):
    """A diameter segment, including tapered or straight shell portions."""

    model_config = ConfigDict(frozen=False)

    section_id: str = ""
    diameter: Quantity = Field(default_factory=Quantity)
    elevation_top: Quantity = Field(default_factory=Quantity)
    elevation_bottom: Quantity = Field(default_factory=Quantity)
    evidence: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ColumnSection(BaseModel):
    """A section of column internals (tray spacing range or packed bed).

    Unified abstraction over TraySpacingSection and PackingSection:
      - Tray: from_no/to_no = tray range, spacing = tray spacing
      - Packed: from_no = section number, diameter/height/elevations = bed dimensions
    """

    model_config = ConfigDict(frozen=False)

    from_no: Optional[int] = None
    to_no: Optional[int] = None
    spacing: Quantity = Field(default_factory=Quantity)
    diameter: Quantity = Field(default_factory=Quantity)
    height: Quantity = Field(default_factory=Quantity)
    elevation_top: Quantity = Field(default_factory=Quantity)
    elevation_bottom: Quantity = Field(default_factory=Quantity)
    evidence: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("from_no", "to_no", mode="before")
    @classmethod
    def _coerce_optional_int(cls, value: Any) -> Optional[int]:
        return _coerce_optional_int(value)


class BetweenRef(BaseModel):
    """Unified reference for port position between internal structures."""

    model_config = ConfigDict(frozen=False)

    type: Literal["tray", "packing"] = "tray"
    refs: list[int] = Field(default_factory=list)

    @field_validator("refs", mode="before")
    @classmethod
    def _coerce_refs(cls, value: Any) -> list[int]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        result: list[int] = []
        seen: set[int] = set()
        for item in value:
            parsed = _coerce_optional_int(item)
            if parsed is None or parsed in seen:
                continue
            seen.add(parsed)
            result.append(parsed)
        return result


class ColumnNozzle(NozzleBase):
    """Nozzle/port information with position reference to internal structures.

    Uses the unified NozzleRole enum from common.py (shared with ReactorNozzle).
    """

    nozzle_role: NozzleRole = NozzleRole.UNKNOWN
    elevation: Quantity = Field(default_factory=Quantity)
    between: BetweenRef = Field(default_factory=BetweenRef)

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


class Column(AssemblyDrawingResult):
    """Structured extraction result for one column.

    Unified model for both tray and packed columns.  ``column_type`` indicates
    the internal structure type; ``count`` / ``numbering_direction`` / ``internals_sections`` are
    interpreted accordingly:

      - TRAY:   count = tray count, numbering_direction = tray numbering direction,
                internals_sections = tray spacing ranges (from_no/to_no + spacing)
      - PACKED: count = packed-bed count, numbering_direction = N/A,
                internals_sections = packed-bed details (from_no + diameter/height/elevations)
    """

    column_type: ColumnType = ColumnType.UNKNOWN
    count: Optional[int] = None
    numbering_direction: NumberingDirection = NumberingDirection.UNKNOWN
    nominal_diameter: Quantity = Field(default_factory=Quantity)
    total_height: Quantity = Field(default_factory=Quantity)
    design_pressure: Quantity = Field(default_factory=Quantity)
    working_pressure: PositionalQuantity = Field(default_factory=PositionalQuantity)
    design_temperature: Quantity = Field(default_factory=Quantity)
    working_temperature: PositionalQuantity = Field(default_factory=PositionalQuantity)
    diameter_sections: list[DiameterSection] = Field(default_factory=list)
    internals_sections: list[ColumnSection] = Field(default_factory=list)
    nozzles: list[ColumnNozzle] = Field(default_factory=list)

    @field_validator("count", mode="before")
    @classmethod
    def _coerce_count(cls, value: Any) -> Optional[int]:
        return _coerce_optional_int(value)

    @model_validator(mode="after")
    def _fill_count_for_packed(self) -> Column:
        if self.count is None and self.column_type == ColumnType.PACKED and self.internals_sections:
            self.count = len(self.internals_sections)
        return self
