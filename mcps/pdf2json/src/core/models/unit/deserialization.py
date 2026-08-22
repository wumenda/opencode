from __future__ import annotations

from typing import Any

from .edges import Port, StreamCondition, StreamEdge
from .enums import (
    BoundaryType,
    EquipmentType,
    InstrumentType,
    KeypointType,
    KEYPOINT_TYPE_MAP,
    NodeType,
    PortCategory,
    PortDirection,
    PortOrientation,
    StreamPhase,
    STREAM_PHASE_ZH_MAP,
)
from .nodes import (
    BoundaryNode,
    InstrumentNode,
    KeypointNode,
    PFDEquipmentNode,
    PFDNode,
)
from .drawing import PFDDrawing
from ..core.safe_construct import safe_model_validate

NODE_TYPE_MAP = {
    "equipment": PFDEquipmentNode,
    "instrument": InstrumentNode,
    "keypoint": KeypointNode,
    "boundary": BoundaryNode,
}


def _parse_phase(phase_str: Any) -> StreamPhase | None:
    if phase_str is None:
        return None
    if isinstance(phase_str, str) and phase_str in STREAM_PHASE_ZH_MAP:
        phase_str = STREAM_PHASE_ZH_MAP[phase_str]
    try:
        return StreamPhase(phase_str)
    except ValueError:
        return StreamPhase.UNKNOWN


class DrawingDeserializer:
    @staticmethod
    def _safe_enum(enum_cls, value, default):
        try:
            return enum_cls(value)
        except (ValueError, KeyError):
            return default

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PFDDrawing:
        raw_nodes = data.get("nodes", [])
        nodes = [
            n for n in (
                cls.node_from_dict(n.get("id", f"node_{i}"), n)
                for i, n in enumerate(raw_nodes)
            ) if n is not None
        ]

        raw_edges = data.get("edges", [])
        edges = [
            e for e in (
                cls.edge_from_dict(e.get("id", f"edge_{i}"), e)
                for i, e in enumerate(raw_edges)
            ) if e is not None
        ]

        return PFDDrawing(
            drawing_id=data.get("drawing_id", ""),
            drawing_name=data.get("drawing_name", ""),
            drawing_number=data.get("drawing_number", ""),
            revision=data.get("revision", ""),
            project=data.get("project", ""),
            unit=data.get("unit", ""),
            nodes=nodes,
            edges=edges,
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def node_from_dict(cls, node_id: str, data: dict[str, Any]) -> PFDNode | None:
        node_type_str = data.get("node_type", "equipment")
        node_class = NODE_TYPE_MAP.get(node_type_str, PFDEquipmentNode)
        kwargs = cls._build_node_kwargs(node_id, data, node_type_str)
        return safe_model_validate(node_class, kwargs)

    @classmethod
    def _build_node_kwargs(
        cls, node_id: str, data: dict[str, Any], node_type_str: str
    ) -> dict[str, Any]:
        effective_type_str = node_type_str
        keypoint_type_value: KeypointType | None = None

        if node_type_str == "keypoint":
            effective_type_str = "keypoint"
            raw_kt = data.get("keypoint_type") or node_type_str or "split"
            keypoint_type_value = KEYPOINT_TYPE_MAP.get(raw_kt, KeypointType.UNKNOWN)
        elif node_type_str == "boundary":
            effective_type_str = "boundary"

        kwargs = {
            "id": node_id,
            "node_type": NodeType(effective_type_str),
            "position": tuple(data.get("position")) if data.get("position") else None,
            "bbox": tuple(data.get("bbox")) if data.get("bbox") else None,
            "name": data.get("name", ""),
        }
        ports_data = data.get("ports", [])
        if ports_data:
            kwargs["ports"] = [
                p for p in (cls._port_from_dict(p) for p in ports_data) if p is not None
            ]
        if effective_type_str == "equipment":
            kwargs["equipment_type"] = EquipmentType(data.get("equipment_type", "other"))
            kwargs["tag"] = data.get("tag", "")
        elif effective_type_str == "instrument":
            kwargs["label"] = data.get("label", "")
            kwargs["instrument_type"] = InstrumentType(data.get("instrument_type", "other"))
            kwargs["tag"] = data.get("tag", "")
            kwargs["measured_variable"] = data.get("measured_variable", "")
        elif effective_type_str == "boundary":
            kwargs["label"] = data.get("label", "")
            raw_bt = data.get("boundary_type", "boundary_in")
            try:
                kwargs["boundary_type"] = BoundaryType(raw_bt)
            except ValueError:
                kwargs["boundary_type"] = BoundaryType.BOUNDARY_IN
            kwargs["equipment_tag"] = data.get("equipment_tag", [])
            kwargs["drawing_id"] = data.get("drawing_id", "")
            kwargs["description"] = data.get("description", "")
        elif effective_type_str == "keypoint":
            kwargs["label"] = data.get("label", "")
            kwargs["degree"] = data.get("degree", 0)
            if keypoint_type_value is not None:
                kwargs["keypoint_type"] = keypoint_type_value
        else:
            kwargs["label"] = data.get("label", "")
        return kwargs

    @classmethod
    def _port_from_dict(cls, data: dict[str, Any]) -> Port | None:
        return safe_model_validate(Port, {
            "id": data.get("id", ""),
            "direction": cls._safe_enum(PortDirection, data.get("direction", "input"), PortDirection.INPUT),
            "category": cls._safe_enum(PortCategory, data.get("category", "process"), PortCategory.PROCESS),
            "label": data.get("label", ""),
            "position": tuple(data.get("position")) if data.get("position") else None,
            "parent_node_id": data.get("parent_node_id", ""),
            "orientation": cls._safe_enum(
                PortOrientation, data.get("orientation", "unknown"), PortOrientation.UNKNOWN
            ),
        })

    @classmethod
    def edge_from_dict(cls, edge_id: str, data: dict[str, Any]) -> StreamEdge | None:
        kwargs = {
            "id": edge_id,
            "source_node_id": data.get("source_node_id", ""),
            "source_port_id": data.get("source_port_id", ""),
            "target_node_id": data.get("target_node_id", ""),
            "target_port_id": data.get("target_port_id", ""),
            "stream_number": data.get("stream_number", ""),
            "stream_name": data.get("stream_name", ""),
            "medium": data.get("medium", ""),
            "control_info": data.get("control_info", {}),
            "metadata": data.get("metadata", {}),
        }
        condition_data = data.get("condition")
        if condition_data:
            condition = cls._condition_from_dict(condition_data)
            if condition is not None:
                kwargs["condition"] = condition
        return safe_model_validate(StreamEdge, kwargs)

    @classmethod
    def _condition_from_dict(cls, data: dict[str, Any]) -> StreamCondition | None:
        phase = _parse_phase(data.get("phase"))
        return safe_model_validate(StreamCondition, {
            "temperature": data.get("temperature"),
            "pressure": data.get("pressure"),
            "mass_flow": data.get("mass_flow"),
            "volume_flow": data.get("volume_flow"),
            "mole_flow": data.get("mole_flow"),
            "phase": phase,
            "composition": data.get("composition", {}),
            "extra": data.get("extra", {}),
        })
