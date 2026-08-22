"""Drawing model for PFD graph."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from .edges import StreamEdge
from .enums import BoundaryType, KeypointType
from .equipment_ports import check_equipment_port_count
from .keypoint_boundary_ports import semantic_port_errors
from .nodes import (
    BoundaryNode,
    KeypointNode,
    PFDEquipmentNode,
    PFDNode,
)


class DrawingInfo(BaseModel):
    """图纸归档元信息（从图注/标题栏提取）。

    与 PFDDrawing 的元信息字段对齐，作为 DrawingInfoExpert 的输出数据模型。
    """

    model_config = ConfigDict(frozen=False)

    drawing_id: str = ""
    drawing_name: str = ""
    drawing_number: str = ""
    revision: str = ""
    project: str = ""
    unit: str = ""


class DrawingValidationResult(BaseModel):
    model_config = ConfigDict(frozen=False)

    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.errors) or bool(self.warnings)


class PFDDrawing(DrawingInfo):
    nodes: list[PFDNode] = Field(default_factory=list)
    edges: list[StreamEdge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _node_map: dict[str, PFDNode] = PrivateAttr(default_factory=dict)
    _edge_map: dict[str, StreamEdge] = PrivateAttr(default_factory=dict)
    _tag_index: dict[str, str] = PrivateAttr(default_factory=dict)
    _source_edge_index: dict[str, list[StreamEdge]] = PrivateAttr(default_factory=dict)
    _target_edge_index: dict[str, list[StreamEdge]] = PrivateAttr(default_factory=dict)
    _index_dirty: bool = PrivateAttr(default=True)

    def _invalidate_index(self) -> None:
        self._index_dirty = True

    def _rebuild_index(self) -> None:
        if not self._index_dirty:
            return
        self._node_map = {n.id: n for n in self.nodes}
        self._edge_map = {e.id: e for e in self.edges}
        self._tag_index = {}
        for node in self.nodes:
            if isinstance(node, PFDEquipmentNode) and node.tag:
                self._tag_index[node.tag] = node.id
            if hasattr(node, "label") and node.label:
                self._tag_index[node.label] = node.id
        self._source_edge_index = {}
        self._target_edge_index = {}
        for edge in self.edges:
            self._source_edge_index.setdefault(edge.source_node_id, []).append(edge)
            self._target_edge_index.setdefault(edge.target_node_id, []).append(edge)
        self._index_dirty = False

    def add_node(self, node: PFDNode) -> None:
        self.nodes.append(node)
        self._node_map[node.id] = node
        self._invalidate_index()

    def remove_node(self, node_id: str) -> Optional[PFDNode]:
        node = self.get_node(node_id)
        if node:
            self.nodes.remove(node)
            del self._node_map[node_id]
            self._invalidate_index()
        return node

    def get_node(self, node_id: str) -> Optional[PFDNode]:
        self._rebuild_index()
        return self._node_map.get(node_id)

    def get_node_by_label(self, label: str) -> Optional[PFDNode]:
        self._rebuild_index()
        node_id = self._tag_index.get(label)
        if node_id is not None:
            return self._node_map.get(node_id)
        return None

    def has_node(self, node_id: str) -> bool:
        self._rebuild_index()
        return node_id in self._node_map

    def add_edge(self, edge: StreamEdge) -> None:
        self.edges.append(edge)
        self._edge_map[edge.id] = edge
        self._invalidate_index()

    def remove_edge(self, edge_id: str) -> Optional[StreamEdge]:
        edge = self.get_edge(edge_id)
        if edge:
            self.edges.remove(edge)
            del self._edge_map[edge_id]
            self._invalidate_index()
        return edge

    def get_edge(self, edge_id: str) -> Optional[StreamEdge]:
        if not self._edge_map:
            self._rebuild_index()
        return self._edge_map.get(edge_id)

    def has_edge(self, edge_id: str) -> bool:
        if not self._edge_map:
            self._rebuild_index()
        return edge_id in self._edge_map

    def get_edges_from_node(self, node_id: str) -> list[StreamEdge]:
        self._rebuild_index()
        return self._source_edge_index.get(node_id, [])

    def get_edges_to_node(self, node_id: str) -> list[StreamEdge]:
        self._rebuild_index()
        return self._target_edge_index.get(node_id, [])

    def get_upstream_nodes(self, node_id: str) -> list[str]:
        return list({e.source_node_id for e in self.get_edges_to_node(node_id)})

    def get_downstream_nodes(self, node_id: str) -> list[str]:
        return list({e.target_node_id for e in self.get_edges_from_node(node_id)})

    def get_equipment_nodes(self) -> list[PFDEquipmentNode]:
        return [n for n in self.nodes if isinstance(n, PFDEquipmentNode)]

    def get_non_equipment_nodes(self) -> list[PFDNode]:
        return [n for n in self.nodes if not isinstance(n, PFDEquipmentNode)]

    def get_boundary_in_nodes(self) -> list[BoundaryNode]:
        return [
            n
            for n in self.nodes
            if isinstance(n, BoundaryNode) and n.boundary_type == BoundaryType.BOUNDARY_IN
        ]

    def get_boundary_out_nodes(self) -> list[BoundaryNode]:
        return [
            n
            for n in self.nodes
            if isinstance(n, BoundaryNode) and n.boundary_type == BoundaryType.BOUNDARY_OUT
        ]

    def get_cross_drawing_in_nodes(self) -> list[BoundaryNode]:
        return [
            n
            for n in self.nodes
            if isinstance(n, BoundaryNode) and n.boundary_type == BoundaryType.CROSS_DRAWING_IN
        ]

    def get_cross_drawing_out_nodes(self) -> list[BoundaryNode]:
        return [
            n
            for n in self.nodes
            if isinstance(n, BoundaryNode) and n.boundary_type == BoundaryType.CROSS_DRAWING_OUT
        ]

    def get_split_nodes(self) -> list[KeypointNode]:
        return [
            n
            for n in self.nodes
            if isinstance(n, KeypointNode) and n.keypoint_type == KeypointType.SPLIT
        ]

    def get_merge_nodes(self) -> list[KeypointNode]:
        return [
            n
            for n in self.nodes
            if isinstance(n, KeypointNode) and n.keypoint_type == KeypointType.MERGE
        ]

    def get_elbow_nodes(self) -> list[KeypointNode]:
        return [
            n
            for n in self.nodes
            if isinstance(n, KeypointNode) and n.keypoint_type == KeypointType.ELBOW
        ]

    def trace_downstream(self, start_node_id: str) -> list[str]:
        visited: set[str] = set()
        stack = [start_node_id]
        order: list[str] = []
        while stack:
            nid = stack.pop()
            if nid in visited:
                continue
            visited.add(nid)
            order.append(nid)
            for downstream_id in self.get_downstream_nodes(nid):
                if downstream_id not in visited:
                    stack.append(downstream_id)
        return order

    def trace_upstream(self, start_node_id: str) -> list[str]:
        visited: set[str] = set()
        stack = [start_node_id]
        order: list[str] = []
        while stack:
            nid = stack.pop()
            if nid in visited:
                continue
            visited.add(nid)
            order.append(nid)
            for upstream_id in self.get_upstream_nodes(nid):
                if upstream_id not in visited:
                    stack.append(upstream_id)
        return order

    def validate(self, *, check_port_constraints: bool = True) -> DrawingValidationResult:
        result = DrawingValidationResult()

        for edge in self.edges:
            src_node = self.get_node(edge.source_node_id)
            if src_node is None:
                result.errors.append(
                    f"Edge '{edge.id}': source node '{edge.source_node_id}' not found"
                )
            tgt_node = self.get_node(edge.target_node_id)
            if tgt_node is None:
                result.errors.append(
                    f"Edge '{edge.id}': target node '{edge.target_node_id}' not found"
                )
            if (
                src_node
                and not isinstance(src_node, KeypointNode)
                and src_node.get_port_by_id(edge.source_port_id) is None
            ):
                result.warnings.append(
                    f"Edge '{edge.id}': source port '{edge.source_port_id}' "
                    f"not found in node '{edge.source_node_id}'"
                )
            if (
                tgt_node
                and not isinstance(tgt_node, KeypointNode)
                and tgt_node.get_port_by_id(edge.target_port_id) is None
            ):
                result.warnings.append(
                    f"Edge '{edge.id}': target port '{edge.target_port_id}' "
                    f"not found in node '{edge.target_node_id}'"
                )
        for node in self.nodes:
            for port in node.ports:
                if port.parent_node_id != node.id:
                    result.errors.append(
                        f"Port '{port.id}' parent_node_id mismatch: "
                        f"expected '{node.id}', got '{port.parent_node_id}'"
                    )
            if check_port_constraints:
                if isinstance(node, BoundaryNode):
                    result.errors.extend(semantic_port_errors(node))
                elif isinstance(node, PFDEquipmentNode):
                    violation = check_equipment_port_count(node)
                    if violation:
                        result.errors.append(
                            f"PFDEquipmentNode({violation.equipment_type}) '{violation.node_id}' port count violation: {'; '.join(violation.violations)}"
                        )

        return result

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict
        return model_to_dict(self)


class PFDTopology(BaseModel):
    """PFD 拓扑容器：分离的 equipment_nodes / boundary_nodes / edges。

    复用 nodes.py / edges.py 中的 PFDEquipmentNode / BoundaryNode / StreamEdge，
    不含位置坐标信息（bbox / position），仅描述纯拓扑结构。
    """

    model_config = ConfigDict(frozen=False)

    equipment_nodes: list[PFDEquipmentNode] = Field(default_factory=list)
    boundary_nodes: list[BoundaryNode] = Field(default_factory=list)
    edges: list[StreamEdge] = Field(default_factory=list)

    _node_index: dict[str, PFDNode] = PrivateAttr(default_factory=dict)

    def rebuild_index(self) -> None:
        self._node_index = {}
        for n in self.equipment_nodes:
            self._node_index[n.id] = n
        for n in self.boundary_nodes:
            self._node_index[n.id] = n

    def get_node(self, node_id: str) -> Optional[PFDNode]:
        if not self._node_index:
            self.rebuild_index()
        return self._node_index.get(node_id)

    def get_upstream_edges(self, node_id: str) -> list[StreamEdge]:
        return [e for e in self.edges if e.target_node_id == node_id]

    def get_downstream_edges(self, node_id: str) -> list[StreamEdge]:
        return [e for e in self.edges if e.source_node_id == node_id]

    def get_upstream_nodes(self, node_id: str) -> list[str]:
        return [e.source_node_id for e in self.get_upstream_edges(node_id)]

    def get_downstream_nodes(self, node_id: str) -> list[str]:
        return [e.target_node_id for e in self.get_downstream_edges(node_id)]

    def validate_references(self) -> list[str]:
        errors: list[str] = []
        all_ids = {n.id for n in self.equipment_nodes} | {n.id for n in self.boundary_nodes}
        for edge in self.edges:
            if edge.source_node_id not in all_ids:
                errors.append(
                    f"Edge {edge.id}: source '{edge.source_node_id}' not found in nodes"
                )
            if edge.target_node_id not in all_ids:
                errors.append(
                    f"Edge {edge.id}: target '{edge.target_node_id}' not found in nodes"
                )
        return errors

    def validate_boundary_direction(self) -> list[str]:
        errors: list[str] = []
        boundary_map = {n.id: n for n in self.boundary_nodes}
        for edge in self.edges:
            src_boundary = boundary_map.get(edge.source_node_id)
            if src_boundary and src_boundary.boundary_type in (
                BoundaryType.BOUNDARY_OUT,
                BoundaryType.CROSS_DRAWING_OUT,
            ):
                errors.append(
                    f"Edge {edge.id}: boundary_out/cross_drawing_out '{edge.source_node_id}' cannot be source"
                )
            tgt_boundary = boundary_map.get(edge.target_node_id)
            if tgt_boundary and tgt_boundary.boundary_type in (
                BoundaryType.BOUNDARY_IN,
                BoundaryType.CROSS_DRAWING_IN,
            ):
                errors.append(
                    f"Edge {edge.id}: boundary_in/cross_drawing_in '{edge.target_node_id}' cannot be target"
                )
        return errors
