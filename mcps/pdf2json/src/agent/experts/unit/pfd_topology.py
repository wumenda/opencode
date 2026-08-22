from __future__ import annotations

import json
from typing import Any, Optional

from src.agent.experts.unit.topology import TopologyExpert
from src.agent.prompts import PromptContext
from src.core.models import PFDTopology


class PFDTopologyExpert(TopologyExpert):
    """带上游上下文的拓扑提取专家。

    上游设备/边界专家已从图纸中识别节点（含 bbox/position），
    本专家注入上下文后仅让 VLM 输出流股边（edges），
    节点由工作流从上游上下文直接合并。
    """

    expert_type = "pfd_topology"
    _prompt_expert_type = "pfd_topology"

    def _build_prompt(self, context: Optional[dict[str, Any]] = None) -> str:
        context_info = self._build_context_info(context) if context else ""
        prompt_context = PromptContext(
            process_description=self.process_description or "未提供工艺流程说明",
            image_size=getattr(self, "_current_image_size", None),
            extra={"context_info": context_info} if context_info else {},
        )
        return self._prompt_builder.build(prompt_context)

    def _build_context_info(self, context: dict[str, Any]) -> str:
        """Build context info text from upstream equipment and boundary_node outputs."""
        lines: list[str] = []

        equipment_list = context.get("equipment", [])
        if isinstance(equipment_list, list) and equipment_list:
            lines.append("【已识别的设备节点（含端口）】")
            lines.append(
                f"设备节点总数: {len([eq for eq in equipment_list if isinstance(eq, dict)])}"
            )
            for eq in equipment_list:
                if not isinstance(eq, dict):
                    continue
                payload = {
                    "id": str(eq.get("id", "")).strip(),
                    "name": str(eq.get("name", "")).strip(),
                    "tag": str(eq.get("tag", "")).strip(),
                    "equipment_type": str(eq.get("equipment_type", "")).strip(),
                    "ports": self._slim_ports_for_context(eq.get("ports", [])),
                }
                lines.append(json.dumps(payload, ensure_ascii=False))

        boundary_nodes = context.get("boundary_node", [])
        if isinstance(boundary_nodes, list) and boundary_nodes:
            lines.append("\n【已识别的边界节点（含端口）】")
            lines.append(
                f"边界节点总数: {len([bn for bn in boundary_nodes if isinstance(bn, dict)])}"
            )
            for bn in boundary_nodes:
                if not isinstance(bn, dict):
                    continue
                payload = {
                    "id": str(bn.get("id", "")).strip(),
                    "boundary_type": str(bn.get("boundary_type", "")).strip(),
                    "equipment_tag": bn.get("equipment_tag", []),
                    "description": str(bn.get("description", "")).strip(),
                    "ports": self._slim_ports_for_context(bn.get("ports", [])),
                }
                lines.append(json.dumps(payload, ensure_ascii=False))

        return "\n".join(lines)

    @staticmethod
    def _slim_ports_for_context(ports: Any) -> list[dict[str, Any]]:
        """Extract port topology fields (id/direction/category/label/orientation/channel/position)
        from upstream port dicts, dropping bbox/parent_node_id.
        """
        if not isinstance(ports, list):
            return []
        slimmed: list[dict[str, Any]] = []
        for p in ports:
            if not isinstance(p, dict):
                continue
            port_id = str(p.get("id", "")).strip()
            if not port_id:
                continue
            slimmed.append(
                {
                    "id": port_id,
                    "direction": str(p.get("direction", "unknown")).strip(),
                    "category": str(p.get("category", "process")).strip(),
                    "label": str(p.get("label", "")).strip(),
                    "orientation": str(p.get("orientation", "unknown")).strip(),
                    "channel": str(p.get("channel", "") or "").strip(),
                    "position": p.get("position"),
                }
            )
        return slimmed

    def _parse(self, raw_response: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info("Parsing topology context response")
        parse_result = self._parse_json_with_recovery(raw_response)

        if not parse_result.success:
            self.logger.warning(f"Failed to parse JSON: {parse_result.warnings}")
            return {
                "topology": PFDTopology().model_dump(),
                "warnings": parse_result.warnings,
            }

        result_json = parse_result.data
        upstream_node_ids = self._collect_upstream_node_ids(context)
        self._normalize_internal_ids(result_json, upstream_node_ids)
        topology = self._build_topology(result_json, upstream_node_ids)

        validation_errors: list[str] = []
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

    @staticmethod
    def _collect_upstream_node_ids(context: Optional[dict[str, Any]]) -> set[str]:
        """从上游上下文收集设备/边界节点 id，用于 VLM 不回传节点时的边校验。"""
        ids: set[str] = set()
        if not context:
            return ids
        for key in ("equipment", "boundary_node"):
            nodes = context.get(key, [])
            if not isinstance(nodes, list):
                continue
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                node_id = str(node.get("id", "")).strip()
                if node_id:
                    ids.add(node_id)
        return ids

    def _build_topology(
        self,
        data: dict[str, Any],
        upstream_node_ids: Optional[set[str]] = None,
    ) -> PFDTopology:
        equipment_nodes = self._parse_equipment_nodes(data.get("equipment_nodes", []))
        boundary_nodes = self._parse_boundary_nodes(data.get("boundary_nodes", []))
        edges = self._parse_edges(data.get("edges", []))

        valid_ids = {n.id for n in equipment_nodes} | {n.id for n in boundary_nodes}
        if not valid_ids and upstream_node_ids:
            valid_ids = set(upstream_node_ids)
        valid_edges = [e for e in edges if self._validate_edge(e, valid_ids)]

        return PFDTopology(
            equipment_nodes=equipment_nodes,
            boundary_nodes=boundary_nodes,
            edges=valid_edges,
        )

    def _normalize_internal_ids(
        self,
        data: dict[str, Any],
        upstream_node_ids: Optional[set[str]] = None,
    ) -> None:
        """规范化 VLM 输出内部的 id 引用，含上游节点 id 回退。"""
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

        if not canonical_to_official and upstream_node_ids:
            for official in upstream_node_ids:
                canonical_to_official.setdefault(self._canonical_id(official), official)

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
