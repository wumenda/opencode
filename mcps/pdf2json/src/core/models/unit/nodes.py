"""Node models for PFD graph."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .edges import Port
from .enums import BoundaryType, EquipmentType, InstrumentType, KeypointType, NodeType


class PFDNode(BaseModel):
    model_config = ConfigDict(frozen=False)

    id: str
    node_type: NodeType = NodeType.EQUIPMENT
    name: str = ""
    ports: list["Port"] = Field(default_factory=list)
    position: Optional[tuple[float, float]] = None
    bbox: Optional[tuple[float, float, float, float]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    page_index: Optional[int] = None

    def get_input_ports(self) -> list[Port]:
        return [p for p in self.ports if p.is_input()]

    def get_output_ports(self) -> list[Port]:
        return [p for p in self.ports if p.is_output()]

    def get_unknown_ports(self) -> list[Port]:
        from .enums import PortDirection

        return [p for p in self.ports if p.direction == PortDirection.UNKNOWN]

    def get_port_by_id(self, port_id: str) -> Optional[Port]:
        for p in self.ports:
            if p.id == port_id:
                return p
        return None

    def add_port(self, port: Port) -> None:
        port.parent_node_id = self.id
        self.ports.append(port)


class PFDEquipmentNode(PFDNode):
    equipment_type: EquipmentType = EquipmentType.OTHER
    tag: str = ""

    def model_post_init(self, __context: Any) -> None:
        self.node_type = NodeType.EQUIPMENT


class InstrumentNode(PFDNode):
    label: str = ""
    instrument_type: InstrumentType = InstrumentType.OTHER
    tag: str = ""
    measured_variable: str = ""
    location: str = ""
    connected_to: str = ""

    def model_post_init(self, __context: Any) -> None:
        self.node_type = NodeType.INSTRUMENT


class BoundaryNode(PFDNode):
    label: str = ""
    boundary_type: BoundaryType = BoundaryType.BOUNDARY_IN
    equipment_tag: list[str] = Field(default_factory=list)
    drawing_id: str = ""
    description: str = ""

    @field_validator("equipment_tag", mode="before")
    @classmethod
    def _normalize_equipment_tag(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return [str(t).strip() for t in v if str(t).strip()]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return []

    def model_post_init(self, __context: Any) -> None:
        self.node_type = NodeType.BOUNDARY


class KeypointNode(PFDNode):
    label: str = ""
    degree: int = 0
    keypoint_type: KeypointType = KeypointType.SPLIT
    ports: list["Port"] = Field(default_factory=list, init=False)

    @field_validator("ports", mode="before")
    @classmethod
    def _force_empty_ports(cls, v: Any) -> list["Port"]:
        return []

    def model_post_init(self, __context: Any) -> None:
        self.node_type = NodeType.KEYPOINT
