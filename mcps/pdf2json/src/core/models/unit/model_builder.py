"""Model builders: parse raw extraction dicts into typed model instances.

These builders convert the loosely-typed dict data produced by LLM extraction
into proper Pydantic model instances (PFDDrawing, PFDTopology),
ensuring the serialized JSON output conforms to the model schema.
"""

from __future__ import annotations

from typing import Any, Optional

from .drawing import PFDDrawing, PFDTopology
from .edges import StreamEdge
from .nodes import (
    BoundaryNode,
    InstrumentNode,
    KeypointNode,
    PFDEquipmentNode,
    PFDNode,
)
from .multi_page import (
    CrossPageLink,
    GlobalPFDGraph,
    UnresolvedCrossDrawingLink,
)
from ..core.serialization import model_to_dict
from ..core.safe_construct import safe_model_validate


# ── Node parsing ──

_NODE_TYPE_MAP = {
    "equipment": PFDEquipmentNode,
    "boundary": BoundaryNode,
    "instrument": InstrumentNode,
    "keypoint": KeypointNode,
}


def build_pfd_node(node_dict: dict[str, Any]) -> PFDNode | None:
    """Parse a node dict into the appropriate PFDNode subclass.

    Uses `node_type` field to determine the subclass. Falls back to
    PFDEquipmentNode if boundary_type is present, else PFDNode.
    Returns ``None`` only if a required field (``id``) fails validation.
    """
    node_type_raw = node_dict.get("node_type", "")
    node_type = str(getattr(node_type_raw, "value", node_type_raw)).strip().lower()
    if not node_type:
        if "boundary_type" in node_dict:
            node_type = "boundary"
        else:
            node_type = "equipment"

    cls = _NODE_TYPE_MAP.get(node_type, PFDNode)
    return safe_model_validate(cls, node_dict)


def build_stream_edge(edge_dict: dict[str, Any]) -> StreamEdge | None:
    """Parse an edge dict into a StreamEdge instance.

    Returns ``None`` if required fields (``source_node_id``, ``target_node_id``)
    fail validation. Optional fields that fail are silently dropped.
    """
    cleaned = dict(edge_dict)
    cleaned.setdefault("source_port_id", "")
    cleaned.setdefault("target_port_id", "")
    return safe_model_validate(StreamEdge, cleaned)


# ── Drawing / Topology builders ──

def build_pfd_drawing(
    page_index: int,
    merged_topology: dict[str, Any],
    page_label: str = "",
    drawing_info: Optional[dict[str, Any]] = None,
) -> PFDDrawing:
    """Build a PFDDrawing model from a merged topology dict.

    Combines equipment_nodes + boundary_nodes into a single `nodes` list,
    and assigns drawing_id from the page index.

    If drawing_info (from DrawingInfoExpert) is provided, its non-empty fields
    override the defaults for drawing_id / drawing_name / drawing_number /
    revision / project / unit.
    """
    equip_nodes = merged_topology.get("equipment_nodes", []) or []
    bnd_nodes = merged_topology.get("boundary_nodes", []) or []
    edges = merged_topology.get("edges", []) or []

    nodes: list[PFDNode] = []
    for eq in equip_nodes:
        node = build_pfd_node(eq)
        if node is not None:
            nodes.append(node)
    for bn in bnd_nodes:
        node = build_pfd_node(bn)
        if node is not None:
            nodes.append(node)

    stream_edges = [e for e in (build_stream_edge(e) for e in edges) if e is not None]

    info = drawing_info or {}
    drawing_id = str(info.get("drawing_id", "")).strip() or f"PFD-{page_index + 1:04d}"
    drawing_name = str(info.get("drawing_name", "")).strip() or page_label or f"第{page_index + 1}页"
    drawing_number = str(info.get("drawing_number", "")).strip()
    revision = str(info.get("revision", "")).strip()
    project = str(info.get("project", "")).strip()
    unit = str(info.get("unit", "")).strip()

    return PFDDrawing(
        drawing_id=drawing_id,
        drawing_name=drawing_name,
        drawing_number=drawing_number,
        revision=revision,
        project=project,
        unit=unit,
        nodes=nodes,
        edges=stream_edges,
    )


def build_pfd_topology(merged_topology: dict[str, Any]) -> PFDTopology:
    """Build a PFDTopology model from a merged topology dict."""
    equip_nodes = merged_topology.get("equipment_nodes", []) or []
    bnd_nodes = merged_topology.get("boundary_nodes", []) or []
    edges = merged_topology.get("edges", []) or []

    return PFDTopology(
        equipment_nodes=[n for n in (build_pfd_node(eq) for eq in equip_nodes) if n is not None],  # type: ignore[arg-type]
        boundary_nodes=[n for n in (build_pfd_node(bn) for bn in bnd_nodes) if n is not None],  # type: ignore[arg-types]
        edges=[e for e in (build_stream_edge(e) for e in edges) if e is not None],
    )


# ── Serialization helpers ──

def pfd_drawing_to_dict(drawing: PFDDrawing) -> dict[str, Any]:
    """Serialize a PFDDrawing to a dict suitable for JSON output."""
    return model_to_dict(drawing)


def pfd_topology_to_dict(topology: PFDTopology) -> dict[str, Any]:
    """Serialize a PFDTopology to a dict suitable for JSON output."""
    return model_to_dict(topology)


# ── Global (multi-page) PFD graph builders ──

def build_global_pfd_graph(global_graph_dict: dict[str, Any]) -> GlobalPFDGraph:
    """Build a GlobalPFDGraph model from a global graph dict.

    The input dict has:
    - nodes: list of node dicts (with page-aware ids)
    - edges: list of edge dicts (in-page + cross-page)
    - cross_page_edges: list of CrossPageLink dicts
    - unresolved_links: list of UnresolvedCrossDrawingLink dicts
    - node_index: dict[str, list[str]]
    """
    nodes = [n for n in (build_pfd_node(nd) for nd in global_graph_dict.get("nodes", []) or []) if n is not None]
    edges = [e for e in (build_stream_edge(ed) for ed in global_graph_dict.get("edges", []) or []) if e is not None]

    cross_page_links = [
        link for link in (
            safe_model_validate(CrossPageLink, link_data)
            for link_data in global_graph_dict.get("cross_page_edges", []) or []
        ) if link is not None
    ]

    unresolved_links = [
        item for item in (
            safe_model_validate(UnresolvedCrossDrawingLink, item_data)
            for item_data in global_graph_dict.get("unresolved_links", []) or []
        ) if item is not None
    ]

    node_index = global_graph_dict.get("node_index", {}) or {}

    return GlobalPFDGraph(
        nodes=nodes,
        edges=edges,
        cross_page_edges=cross_page_links,
        unresolved_links=unresolved_links,
        node_index=node_index,
    )


def global_pfd_graph_to_dict(graph: GlobalPFDGraph) -> dict[str, Any]:
    """Serialize a GlobalPFDGraph to a dict suitable for JSON output.

    输出固定包含 5 个字段：nodes、edges、cross_page_edges、unresolved_links、node_index。
    edges 字段中移除 waypoints（global_graph.json 不需要路由坐标信息）。
    """
    result = model_to_dict(graph)
    for edge in result.get("edges", []) or []:
        edge.pop("waypoints", None)
    return result
