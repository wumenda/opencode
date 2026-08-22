"""
Boundary Node Expert - 边界节点提取专家
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Optional

from src.agent.experts.core.base import BaseExpert
from src.agent.utils.boundary_port_utils import ensure_correct_boundary_ports
from src.agent.utils.node_parser import NodeParser
from src.agent.prompts import get_prompt_builder, PromptContext
from src.core import parse_json_safely
from src.core.models import (
    PFDNode,
    BoundaryNode,
    NodeType,
    BoundaryType,
    has_valid_semantic_ports,
    semantic_port_errors,
    safe_model_validate,
)

if TYPE_CHECKING:
    from src.agent.preprocessor.preprocessor import ExpertImagePreprocessor
    from src.core.client import VisionAPIClient
    from src.core.infra.config import Settings


class BoundaryNodeExpert(BaseExpert):
    """Expert for identifying boundary nodes (boundary_in, boundary_out, cross_drawing_in, cross_drawing_out)."""

    expert_type = "boundary_node"
    _PFD_DRAWING_ID_PATTERN = re.compile(r"^PFD[-–\s]?\d{3,5}$", re.IGNORECASE)
    _EQUIPMENT_TAG_PATTERN = re.compile(
        r"([A-Z]{1,3}-\d{4,5}[A-Z]?(?:(?:/[A-Z]{1,3}-\d{4,5}[A-Z]?)|(?:/[A-Z]))*)"
    )

    def __init__(
        self,
        settings: Optional["Settings"] = None,
        process_description: str = "",
        enable_preprocessing: bool = True,
        client: Optional["VisionAPIClient"] = None,
        preprocessor: Optional["ExpertImagePreprocessor"] = None,
    ) -> None:
        super().__init__(
            settings,
            enable_preprocessing=enable_preprocessing,
            client=client,
            preprocessor=preprocessor,
        )
        self.process_description = process_description
        self._prompt_builder = get_prompt_builder("boundary_node", self._prompt_version)

    def _extract(self, image_path: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Extract raw boundary node information from image."""

        self.logger.info(f"Extracting boundary nodes from: {image_path}")
        prompt = self._build_prompt(context)

        raw_response, image_metadata, _ = self.client.call_api_with_expert_config(
            image_path,
            prompt,
            self.provider_config,
            self.expert_config,
            max_dimension=self.max_image_size,
        )

        return {
            "raw_response": raw_response,
            "image_path": image_path,
            "image_metadata": image_metadata,
        }

    def _build_prompt(self, context: Optional[dict[str, Any]]) -> str:
        prompt_context = PromptContext(
            process_description=self.process_description or "未提供工艺流程说明",
            image_size=getattr(self, "_current_image_size", None),
        )
        return self._prompt_builder.build(prompt_context)

    def _parse(self, raw_response: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Parse raw response into structured boundary node data."""

        self.logger.info("Parsing boundary node response")
        result_json = parse_json_safely(raw_response, expert_type=self.expert_type)

        if result_json is None:
            self.logger.warning("Failed to parse JSON")
            return {"boundary_node": [], "warnings": ["JSON parse failed"]}

        boundary_nodes: list[PFDNode] = []

        for node_key, node_list in result_json.items():
            if not isinstance(node_list, list):
                self.logger.warning(f"Expected list for key {node_key}, got {type(node_list)}")
                continue

            for node_data in node_list:
                try:
                    if not isinstance(node_data, dict):
                        self.logger.warning(f"Expected dict in node list, got {type(node_data)}")
                        continue

                    if "id" not in node_data and node_key:
                        node_data["id"] = node_key

                    node = self._parse_node(node_data)
                    if node is not None:
                        if self._validate_boundary_ports(node):
                            boundary_nodes.append(node)
                        else:
                            errors = semantic_port_errors(node)
                            self.logger.warning(
                                "Dropping invalid boundary node %s: port validation failed [%s]",
                                node.id,
                                "; ".join(errors),
                            )
                except Exception as e:
                    self.logger.warning(f"Failed to parse boundary node {node_key}: {e}")

        return {
            "boundary_node": [n.model_dump() for n in boundary_nodes],
        }

    def _validate_boundary_ports(self, node: PFDNode) -> bool:
        """Validate port constraints for boundary/cross-drawing nodes."""
        return has_valid_semantic_ports(node)

    def _parse_node(self, node_data: dict[str, Any]) -> Optional[PFDNode]:
        node_type_raw = node_data.get("node_type", "boundary")
        node_id = str(node_data.get("id") or "")

        vlm_ports_data = node_data.get("ports", [])
        ports = NodeParser.parse_ports(node_id, vlm_ports_data)

        base_kwargs = {
            "id": str(node_data.get("id") or ""),
            "name": str(node_data.get("name") or ""),
            "label": str(node_data.get("label") or ""),
            "ports": ports,
            "position": tuple(node_data.get("position")) if node_data.get("position") else None,
            "bbox": tuple(node_data.get("bbox")) if node_data.get("bbox") else None,
        }

        if node_type_raw == "boundary":
            if "boundary_type" not in node_data:
                node_data["boundary_type"] = "boundary_in"
        try:
            node_type = NodeType(node_type_raw)
        except Exception:
            self.logger.warning(f"Unknown node type '{node_type_raw}', skipping node")
            return None

        normalized_boundary_type = self._cross_type_from_pfd_boundary(node_type, node_data)
        if normalized_boundary_type is not None:
            drawing_id, description, equipment_tag = self._extract_boundary_fields(
                node_data, normalized_boundary_type
            )
            base_kwargs["ports"] = self._ensure_correct_ports(
                node_id, ports, normalized_boundary_type, vlm_ports_data
            )
            kwargs = {
                **base_kwargs,
                "boundary_type": normalized_boundary_type,
                "equipment_tag": equipment_tag,
                "drawing_id": drawing_id,
                "description": description,
            }
            return safe_model_validate(BoundaryNode, kwargs, logger=self.logger)

        if node_type == NodeType.BOUNDARY:
            boundary_type_str = node_data.get("boundary_type", "")
            try:
                boundary_type = BoundaryType(boundary_type_str)
            except Exception:
                boundary_type = BoundaryType.BOUNDARY_IN
            drawing_id, description, equipment_tag = self._extract_boundary_fields(
                node_data, boundary_type
            )
            base_kwargs["ports"] = self._ensure_correct_ports(
                node_id, ports, boundary_type, vlm_ports_data
            )
            return BoundaryNode(
                **base_kwargs,
                boundary_type=boundary_type,
                equipment_tag=equipment_tag,
                drawing_id=drawing_id,
                description=description,
            )

        return None

    def _ensure_correct_ports(
        self,
        node_id: str,
        parsed_ports: list,
        boundary_type: BoundaryType,
        vlm_ports_data: list[dict[str, Any]],
    ) -> list:
        return ensure_correct_boundary_ports(node_id, parsed_ports, boundary_type, vlm_ports_data)

    def _extract_boundary_fields(
        self, node_data: dict[str, Any], boundary_type: BoundaryType
    ) -> tuple[str, str, list[str]]:
        drawing_id = str(node_data.get("drawing_id") or "")
        description = str(node_data.get("description") or "")
        equipment_tag = node_data.get("equipment_tag") or []
        if not equipment_tag:
            if boundary_type == BoundaryType.CROSS_DRAWING_IN:
                stream_label = node_data.get("source_stream_label", "") or node_data.get(
                    "medium", ""
                )
            elif boundary_type == BoundaryType.CROSS_DRAWING_OUT:
                stream_label = node_data.get("destination_stream_label", "") or node_data.get(
                    "medium", ""
                )
            else:
                stream_label = ""
            tag_str = self._extract_equipment_tag(stream_label)
            if tag_str:
                equipment_tag = [tag_str]
        return drawing_id, description, equipment_tag

    def _cross_type_from_pfd_boundary(
        self, node_type: NodeType, node_data: dict[str, Any]
    ) -> Optional[BoundaryType]:
        if node_type != NodeType.BOUNDARY:
            return None
        stream_id = str(node_data.get("stream_id", "")).strip()
        if not self._PFD_DRAWING_ID_PATTERN.match(stream_id):
            return None
        boundary_type_str = node_data.get("boundary_type", "")
        if boundary_type_str == BoundaryType.BOUNDARY_IN:
            return BoundaryType.CROSS_DRAWING_IN
        if boundary_type_str == BoundaryType.BOUNDARY_OUT:
            return BoundaryType.CROSS_DRAWING_OUT
        return None

    def _extract_equipment_tag(self, text: str) -> str:
        for match in self._EQUIPMENT_TAG_PATTERN.finditer(text or ""):
            tag = match.group(1).replace(" ", "")
            if not tag.upper().startswith("PFD-"):
                return tag
        return ""
