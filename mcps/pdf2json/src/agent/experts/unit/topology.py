from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from src.agent.experts.core.base import BaseExpert
from src.agent.prompts import get_prompt_builder, PromptContext
from src.core.models import (
    BoundaryNode,
    BoundaryType,
    EquipmentType,
    PFDTopology,
    PFDEquipmentNode,
    Port,
    PortCategory,
    PortDirection,
    PortOrientation,
    StreamCondition,
    StreamEdge,
    StreamPhase,
    safe_model_validate,
)

if TYPE_CHECKING:
    from src.agent.preprocessor import ExpertImagePreprocessor
    from src.core import Settings, VisionAPIClient


class TopologyExpert(BaseExpert):
    """装置级拓扑提取专家（独立提取，不依赖上游上下文）。

    直接从 PFD 图纸中识别设备节点、边界节点、端口和流股边，
    并提取 bbox/position 坐标信息。
    """

    expert_type = "topology"
    _prompt_expert_type = "topology"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        process_description: str = "",
        enable_preprocessing: bool = True,
        client: Optional[VisionAPIClient] = None,
        preprocessor: Optional[ExpertImagePreprocessor] = None,
        prompt_version: Optional[str] = None,
    ) -> None:
        super().__init__(
            settings,
            enable_preprocessing=enable_preprocessing,
            client=client,
            preprocessor=preprocessor,
            prompt_version=prompt_version,
        )
        self.process_description = process_description
        self._prompt_builder = self._resolve_builder(
            self._prompt_expert_type, self._prompt_version
        )

    @staticmethod
    def _resolve_builder(expert_type: str, version: Optional[str]):
        try:
            return get_prompt_builder(expert_type, version)
        except ValueError:
            return get_prompt_builder(expert_type, "v1")

    def _extract(self, image_path: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info(f"Extracting topology from: {image_path}")
        result = self._call_vlm(image_path, context)
        result["image_path"] = image_path
        return result

    def _build_prompt(self, context: Optional[dict[str, Any]] = None) -> str:
        prompt_context = PromptContext(
            process_description=self.process_description or "未提供工艺流程说明",
            image_size=getattr(self, "_current_image_size", None),
        )
        return self._prompt_builder.build(prompt_context)

    def _parse(self, raw_response: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info("Parsing topology response")
        parse_result = self._parse_json_with_recovery(raw_response)

        if not parse_result.success:
            self.logger.warning(f"Failed to parse JSON: {parse_result.warnings}")
            return {
                "topology": PFDTopology().model_dump(),
                "warnings": parse_result.warnings,
            }

        result_json = parse_result.data
        self._normalize_internal_ids(result_json)
        topology = self._build_topology(result_json)

        validation_errors: list[str] = []
        validation_errors.extend(topology.validate_references())
        validation_errors.extend(topology.validate_boundary_direction())

        warnings = parse_result.warnings.copy()
        if parse_result.recovery_level > 0:
            warnings.append(f"JSON recovery level: {parse_result.recovery_level}")
        for err in validation_errors:
            warnings.append(err)
            self.logger.warning(f"Topology validation: {err}")

        return {
            "topology": topology.model_dump(),
            "warnings": warnings,
            "recovery_level": parse_result.recovery_level,
        }

    def _build_topology(self, data: dict[str, Any]) -> PFDTopology:
        equipment_nodes = self._parse_equipment_nodes(data.get("equipment_nodes", []))
        boundary_nodes = self._parse_boundary_nodes(data.get("boundary_nodes", []))
        edges = self._parse_edges(data.get("edges", []))

        valid_ids = {n.id for n in equipment_nodes} | {n.id for n in boundary_nodes}
        valid_edges = [e for e in edges if self._validate_edge(e, valid_ids)]

        return PFDTopology(
            equipment_nodes=equipment_nodes,
            boundary_nodes=boundary_nodes,
            edges=valid_edges,
        )

    @staticmethod
    def _canonical_id(value: Any) -> str:
        """归一化 id：去空白、统一小写，用于宽松匹配。"""
        return str(value or "").strip().lower()

    def _normalize_internal_ids(self, data: dict[str, Any]) -> None:
        """规范化 VLM 单次输出内部的 id 引用，避免边被误丢。"""
        eq_nodes = data.get("equipment_nodes", []) or []
        bnd_nodes = data.get("boundary_nodes", []) or []
        edges = data.get("edges", []) or []

        canonical_to_official: dict[str, str] = {}
        for n in list(eq_nodes) + list(bnd_nodes):
            if not isinstance(n, dict):
                continue
            official = str(n.get("id", "")).strip()
            if not official:
                continue
            n["id"] = official
            key = self._canonical_id(official)
            canonical_to_official.setdefault(key, official)

        remapped = 0
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            for field in ("source_node_id", "target_node_id"):
                raw = edge.get(field, "")
                official = canonical_to_official.get(self._canonical_id(raw))
                if official and official != raw:
                    edge[field] = official
                    remapped += 1
                elif isinstance(raw, str) and raw != raw.strip():
                    edge[field] = raw.strip()
        if remapped:
            self.logger.info(
                f"Normalized {remapped} edge endpoint id(s) to match node ids (case/whitespace)"
            )

    def _parse_equipment_nodes(self, data: list[dict[str, Any]]) -> list[PFDEquipmentNode]:
        nodes: list[PFDEquipmentNode] = []
        for item in data:
            equipment_type_raw = item.get("equipment_type", "other")
            try:
                EquipmentType(equipment_type_raw)
            except Exception:
                equipment_type_raw = "other"

            tag = str(item.get("tag") or "").strip()
            node = safe_model_validate(PFDEquipmentNode, {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "tag": tag,
                "equipment_type": equipment_type_raw,
                "bbox": self._parse_bbox(item.get("bbox")),
            }, logger=self.logger)
            if node is None:
                continue
            for port in self._parse_ports(item.get("ports", [])):
                node.add_port(port)
            nodes.append(node)
        return nodes

    def _parse_boundary_nodes(self, data: list[dict[str, Any]]) -> list[BoundaryNode]:
        nodes: list[BoundaryNode] = []
        for item in data:
            boundary_type_raw = item.get("boundary_type", "boundary_in")
            try:
                BoundaryType(boundary_type_raw)
            except Exception:
                boundary_type_raw = "boundary_in"

            node = safe_model_validate(BoundaryNode, {
                "id": str(item.get("id") or ""),
                "label": str(item.get("label") or ""),
                "boundary_type": boundary_type_raw,
                "equipment_tag": item.get("equipment_tag") or [],
                "drawing_id": str(item.get("drawing_id") or ""),
                "description": str(item.get("description") or ""),
                "bbox": self._parse_bbox(item.get("bbox")),
            }, logger=self.logger)
            if node is None:
                continue
            for port in self._parse_ports(item.get("ports", [])):
                node.add_port(port)
            nodes.append(node)
        return nodes

    def _parse_edges(self, data: list[dict[str, Any]]) -> list[StreamEdge]:
        edges: list[StreamEdge] = []
        for item in data:
            condition = self._parse_condition(item.get("condition", {}))
            source = str(item.get("source_node_id") or "").strip()
            target = str(item.get("target_node_id") or "").strip()
            edge = safe_model_validate(StreamEdge, {
                "id": str(item.get("id") or ""),
                "source_node_id": source,
                "target_node_id": target,
                "source_port_id": str(item.get("source_port_id", "") or ""),
                "target_port_id": str(item.get("target_port_id", "") or ""),
                "stream_number": str(item.get("stream_number") or ""),
                "stream_name": str(item.get("stream_name") or ""),
                "medium": str(item.get("medium") or ""),
                "condition": condition,
            }, required_fields={"source_node_id", "target_node_id"}, logger=self.logger)
            if edge is not None:
                edges.append(edge)
        return edges

    def _parse_ports(self, data: list[dict[str, Any]]) -> list[Port]:
        ports: list[Port] = []
        for item in data:
            port_id = str(item.get("id") or "").strip()
            if not port_id:
                continue

            direction_raw = str(item.get("direction", "unknown")).strip()
            try:
                direction = PortDirection(direction_raw)
            except Exception:
                direction = PortDirection.UNKNOWN

            category_raw = str(item.get("category", "process")).strip()
            try:
                category = PortCategory(category_raw)
            except Exception:
                category = PortCategory.PROCESS

            orientation_raw = str(item.get("orientation", "unknown")).strip()
            try:
                orientation = PortOrientation(orientation_raw)
            except Exception:
                orientation = PortOrientation.UNKNOWN

            port = safe_model_validate(Port, {
                "id": port_id,
                "direction": direction,
                "category": category,
                "label": str(item.get("label") or "").strip(),
                "orientation": orientation,
                "position": self._parse_position(item.get("position")),
                "channel": str(item.get("channel", "") or "").strip(),
            }, logger=self.logger)
            if port is not None:
                ports.append(port)
        return ports

    @staticmethod
    def _parse_bbox(value: Any) -> Optional[tuple[float, float, float, float]]:
        """解析 bbox [x_min, y_min, x_max, y_max]，归一化坐标。"""
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            return None
        try:
            return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_position(value: Any) -> Optional[tuple[float, float]]:
        """解析 position [x, y]，归一化坐标。"""
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return None
        try:
            return (float(value[0]), float(value[1]))
        except (TypeError, ValueError):
            return None

    def _parse_condition(self, data: dict[str, Any]) -> StreamCondition:
        if not isinstance(data, dict):
            return StreamCondition()

        phase_raw = data.get("phase", "unknown")
        try:
            StreamPhase(phase_raw)
        except Exception:
            phase_raw = "unknown"

        raw_composition = data.get("composition", {}) or {}
        composition: dict[str, float] = {}
        if isinstance(raw_composition, dict):
            for key, value in raw_composition.items():
                if value is None or value == "":
                    continue
                try:
                    composition[str(key)] = float(value)
                except (TypeError, ValueError):
                    self.logger.debug(
                        f"Skip non-numeric composition entry: {key}={value!r}"
                    )

        return safe_model_validate(StreamCondition, {
            "temperature": data.get("temperature"),
            "pressure": data.get("pressure"),
            "mass_flow": data.get("mass_flow"),
            "volume_flow": data.get("volume_flow"),
            "mole_flow": data.get("mole_flow"),
            "phase": phase_raw,
            "composition": composition,
        }, logger=self.logger) or StreamCondition()

    def _validate_edge(self, edge: StreamEdge, valid_ids: set[str]) -> bool:
        if not edge.source_node_id or not edge.target_node_id:
            self.logger.warning(f"Edge {edge.id} has empty source/target, dropping")
            return False
        if edge.source_node_id not in valid_ids:
            self.logger.warning(
                f"Edge {edge.id} references unknown source '{edge.source_node_id}', dropping"
            )
            return False
        if edge.target_node_id not in valid_ids:
            self.logger.warning(
                f"Edge {edge.id} references unknown target '{edge.target_node_id}', dropping"
            )
            return False
        return True
