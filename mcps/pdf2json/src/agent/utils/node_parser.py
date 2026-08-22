from typing import Any

from src.core.models import (
    PFDNode,
    Port,
    PortDirection,
    PortCategory,
    KeypointNode,
    KeypointType,
    BoundaryNode,
    NodeType,
    safe_model_validate,
)

_NODE_TYPE_MAP = {
    "keypoint": (KeypointNode, None),
    "boundary": (BoundaryNode, None),
}

_KEYPOINT_TYPE_MAP = {
    "split": KeypointType.SPLIT,
    "merge": KeypointType.MERGE,
    "elbow": KeypointType.ELBOW,
    "crossing_h": KeypointType.CROSSING_H,
    "crossing_v": KeypointType.CROSSING_V,
    "unknown": KeypointType.UNKNOWN,
    "invalid": KeypointType.INVALID,
}


class NodeParser:
    @staticmethod
    def parse_ports(node_id: str, ports_data: list[dict[str, Any]]) -> list[Port]:
        ports: list[Port] = []
        for port_data in ports_data:
            try:
                direction = PortDirection(port_data.get("direction", PortDirection.INPUT))
            except Exception:
                direction = PortDirection.INPUT
            try:
                category = PortCategory(port_data.get("category", PortCategory.PROCESS))
            except Exception:
                category = PortCategory.PROCESS
            port = safe_model_validate(Port, {
                "id": str(port_data.get("id") or ""),
                "direction": direction,
                "category": category,
                "label": str(port_data.get("label") or ""),
                "position": tuple(port_data.get("position")) if port_data.get("position") else None,
                "parent_node_id": str(port_data.get("parent_node_id") or node_id or ""),
            })
            if port is not None:
                ports.append(port)
        return ports

    @staticmethod
    def build_base_kwargs(node_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(node_data.get("id") or ""),
            "node_type": NodeType(node_data.get("node_type", "keypoint")),
            "position": tuple(node_data.get("position")) if node_data.get("position") else None,
            "bbox": tuple(node_data.get("bbox")) if node_data.get("bbox") else None,
            "label": node_data.get("label", ""),
        }

    @staticmethod
    def dispatch_node(node_type: str, base_kwargs: dict[str, Any], **extra) -> PFDNode:
        entry = _NODE_TYPE_MAP.get(node_type)
        if entry is None:
            raise ValueError(f"Unknown node type: {node_type}")
        node_class, _ = entry
        kwargs = {**base_kwargs, **extra}
        if node_class is KeypointNode and "keypoint_type" not in kwargs:
            kp_type = _KEYPOINT_TYPE_MAP.get(node_type, KeypointType.UNKNOWN)
            kwargs["keypoint_type"] = kp_type
        return node_class(**kwargs)
