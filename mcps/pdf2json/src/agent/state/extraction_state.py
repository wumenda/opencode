from __future__ import annotations

import warnings
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExtractionState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    outputs: dict[str, Any] = Field(default_factory=dict)

    def get(self, expert_type: str) -> Optional[Any]:
        return self.outputs.get(expert_type)

    def set(self, expert_type: str, output: Any) -> None:
        self.outputs[expert_type] = output

    @property
    def equipment_output(self) -> Optional[Any]:
        return self.outputs.get("equipment")

    @equipment_output.setter
    def equipment_output(self, value: Optional[Any]):
        self.set("equipment", value)

    @property
    def stream_edge_output(self) -> Optional[Any]:
        return self.outputs.get("stream_edge")

    @stream_edge_output.setter
    def stream_edge_output(self, value: Optional[Any]):
        self.set("stream_edge", value)

    @property
    def boundary_node_output(self) -> Optional[Any]:
        return self.outputs.get("boundary_node")

    @boundary_node_output.setter
    def boundary_node_output(self, value: Optional[Any]):
        self.set("boundary_node", value)

    @property
    def keypoint_output(self) -> Optional[Any]:
        return self.outputs.get("keypoint")

    @keypoint_output.setter
    def keypoint_output(self, value: Optional[Any]):
        self.set("keypoint", value)

    @property
    def keypoint_filter_output(self) -> Optional[Any]:
        return self.outputs.get("keypoint_filter")

    @keypoint_filter_output.setter
    def keypoint_filter_output(self, value: Optional[Any]):
        self.set("keypoint_filter", value)

    @property
    def keypoint_classifier_output(self) -> Optional[Any]:
        return self.outputs.get("keypoint_classifier")

    @keypoint_classifier_output.setter
    def keypoint_classifier_output(self, value: Optional[Any]):
        self.set("keypoint_classifier", value)

    @property
    def port_detection_output(self) -> Optional[Any]:
        return self.outputs.get("port_detection")

    @port_detection_output.setter
    def port_detection_output(self, value: Optional[Any]):
        self.set("port_detection", value)

    @property
    def equipment_port_output(self) -> Optional[Any]:
        warnings.warn(
            "equipment_port_output is deprecated, use port_detection_output instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.outputs.get("port_detection")

    @equipment_port_output.setter
    def equipment_port_output(self, value: Optional[Any]):
        warnings.warn(
            "equipment_port_output is deprecated, use port_detection_output instead",
            DeprecationWarning,
            stacklevel=2,
        )
        self.set("port_detection", value)

    @property
    def arrow_detection_output(self) -> Optional[Any]:
        return self.outputs.get("arrow_detection")

    @arrow_detection_output.setter
    def arrow_detection_output(self, value: Optional[Any]):
        self.set("arrow_detection", value)

    @property
    def control_loop_output(self) -> Optional[Any]:
        return self.outputs.get("control_loop")

    @control_loop_output.setter
    def control_loop_output(self, value: Optional[Any]):
        self.set("control_loop", value)

    @property
    def port_classification_output(self) -> Optional[Any]:
        return self.outputs.get("port_classification")

    @port_classification_output.setter
    def port_classification_output(self, value: Optional[Any]):
        self.set("port_classification", value)

    @property
    def drawing_info_output(self) -> Optional[Any]:
        return self.outputs.get("drawing_info")

    @drawing_info_output.setter
    def drawing_info_output(self, value: Optional[Any]):
        self.set("drawing_info", value)

    @property
    def topology_output(self) -> Optional[Any]:
        return self.outputs.get("topology")

    @topology_output.setter
    def topology_output(self, value: Optional[Any]):
        self.set("topology", value)
