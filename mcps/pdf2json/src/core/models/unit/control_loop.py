"""Control loop models for PFD graph."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ControlLoopNode(BaseModel):
    model_config = ConfigDict(frozen=False)

    id: str
    loop_tag: str = ""
    controller_id: str = ""
    controller_tag: str = ""
    controller_type: str = ""
    controlled_variable: str = ""
    measuring_element_id: str = ""
    measuring_element_tag: str = ""
    final_control_element_id: str = ""
    final_control_element_tag: str = ""
    final_control_element_type: str = ""
    setpoint_value: str = ""
    control_action: str = ""
    process_node_ids: list[str] = Field(default_factory=list)
    process_node_tags: list[str] = Field(default_factory=list)
    signal_connections: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
