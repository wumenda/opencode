"""Multi-page drawing models for PFD graph."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from .drawing import PFDDrawing
from .edges import StreamEdge
from .nodes import PFDNode
from ..core.serialization import model_to_dict


class DrawingRef(BaseModel):
    model_config = ConfigDict(frozen=False)

    pdf_id: str
    page_index: int
    page_label: str = ""


class CrossPageLink(BaseModel):
    model_config = ConfigDict(frozen=False)

    from_node_id: str
    from_page_index: int
    to_node_id: str
    to_page_index: int
    link_type: str = "cross_page_stitch"
    status: str = ""
    match_reason: str = ""


class PageGraphBundle(BaseModel):
    model_config = ConfigDict(frozen=False)

    drawing_ref: DrawingRef
    pfd_drawing: "PFDDrawing"
    composition_table_data: Optional[dict[str, Any]] = None


class UnresolvedCrossDrawingLink(BaseModel):
    model_config = ConfigDict(frozen=False)

    node_id: str
    page_index: int
    boundary_type: str
    equipment_tags: list[str]
    unresolved_tags: list[str]
    description: str = ""


class GlobalPFDGraph(BaseModel):
    model_config = ConfigDict(frozen=False)

    nodes: list[PFDNode] = Field(default_factory=list)
    edges: list[StreamEdge] = Field(default_factory=list)
    cross_page_edges: list[CrossPageLink]
    unresolved_links: list[UnresolvedCrossDrawingLink] = Field(default_factory=list)
    node_index: dict[str, list[str]]

    _node_map: dict[str, PFDNode] = PrivateAttr(default_factory=dict)
    _edge_map: dict[str, StreamEdge] = PrivateAttr(default_factory=dict)

    def get_node(self, node_id: str) -> Optional[PFDNode]:
        if not self._node_map:
            self._node_map = {n.id: n for n in self.nodes}
        return self._node_map.get(node_id)

    def has_node(self, node_id: str) -> bool:
        if not self._node_map:
            self._node_map = {n.id: n for n in self.nodes}
        return node_id in self._node_map

    def get_edge(self, edge_id: str) -> Optional[StreamEdge]:
        if not self._edge_map:
            self._edge_map = {e.id: e for e in self.edges}
        return self._edge_map.get(edge_id)

    def has_edge(self, edge_id: str) -> bool:
        if not self._edge_map:
            self._edge_map = {e.id: e for e in self.edges}
        return edge_id in self._edge_map

    def to_dict(self) -> dict[str, Any]:
        return model_to_dict(self)


class MultiPageExtractionResult(BaseModel):
    model_config = ConfigDict(frozen=False, arbitrary_types_allowed=True)

    global_graph: GlobalPFDGraph
    page_graphs: list[PageGraphBundle]
    cross_page_mapping_table: list[dict[str, Any]]
    unresolved_links: list[dict[str, Any]]
    validation_report: Any = None
    correction_applied: bool = False
    pre_correction_error_count: int = 0
    post_correction_error_count: int = 0
    output_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return model_to_dict(self)
