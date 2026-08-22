"""Edge and Port models for PFD graph."""

from __future__ import annotations

from typing import Any, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    PortCategory,
    PortDirection,
    PortOrientation,
    StreamPhase,
)


class Port(BaseModel):
    model_config = ConfigDict(frozen=False)

    id: str
    direction: PortDirection
    category: PortCategory = PortCategory.PROCESS
    label: str = ""
    position: Optional[tuple[float, float]] = None
    parent_node_id: str = ""
    orientation: PortOrientation = PortOrientation.UNKNOWN
    channel: str = ""

    def is_input(self) -> bool:
        return self.direction == PortDirection.INPUT

    def is_output(self) -> bool:
        return self.direction == PortDirection.OUTPUT


class StreamCondition(BaseModel):
    model_config = ConfigDict(frozen=False)

    temperature: Optional[Union[float, str]] = None
    pressure: Optional[Union[float, str]] = None
    mass_flow: Optional[Union[float, str]] = None
    volume_flow: Optional[Union[float, str]] = None
    mole_flow: Optional[Union[float, str]] = None
    phase: StreamPhase = StreamPhase.UNKNOWN
    composition: dict[str, float] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class StreamEdge(BaseModel):
    model_config = ConfigDict(frozen=False)

    id: str
    source_node_id: str
    source_port_id: str = ""
    target_node_id: str
    target_port_id: str = ""
    stream_number: str = ""
    stream_name: str = ""
    medium: str = ""
    condition: StreamCondition = Field(default_factory=StreamCondition)
    control_info: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    page_index: Optional[int] = None
    source_node_pageindex: Optional[int] = None
    target_node_pageindex: Optional[int] = None
    waypoints: list[tuple[float, float]] = Field(default_factory=list)
