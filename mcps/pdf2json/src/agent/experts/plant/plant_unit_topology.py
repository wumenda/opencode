"""Plant-unit topology experts and drawing assembly."""

from __future__ import annotations

import json
from typing import Any, Optional, cast

from src.agent.experts.core.base import BaseExpert
from src.agent.models import ExpertOutput
from src.agent.prompts import PromptContext, get_prompt_builder
from src.core import Settings, VisionAPIClient
from src.core.io.json_utils import parse_json_with_recovery
from src.core.models import (
    PlantUnitDrawing,
    PlantUnitEdge,
    PlantUnitNode,
    safe_model_validate,
)

from .plant_unit_parsers import _parse_edges_from_outlets


class PlantUnitTopologyExpert(BaseExpert):
    """Extract material-labeled connections between whole-plant units."""

    expert_type = "plant_unit_topology"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        enable_preprocessing: bool = False,
        prompt_version: Optional[str] = None,
        client: Optional[VisionAPIClient] = None,
    ) -> None:
        super().__init__(
            settings=settings,
            enable_preprocessing=enable_preprocessing,
            prompt_version=prompt_version,
            client=client,
        )
        self._prompt_builder = get_prompt_builder("plant_unit_topology", self._prompt_version)

    def _extract(self, image_path: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info(f"Extracting plant unit topology from: {image_path}")
        return cast(dict[str, Any], self._call_vlm(image_path, context=context))

    def _build_prompt(self, context: Optional[dict[str, Any]] = None) -> str:
        context = context if isinstance(context, dict) else {}
        plant_units = context.get("plant_unit", [])
        text_destinations = context.get("text_destinations", [])
        prompt_context = PromptContext(
            image_size=getattr(self, "_current_image_size", None),
            extra={
                "plant_unit_context": json.dumps(plant_units, ensure_ascii=False, indent=2),
                "text_destination_context": json.dumps(
                    text_destinations, ensure_ascii=False, indent=2
                ),
            },
        )
        return cast(str, self._prompt_builder.build(prompt_context))

    def _parse(self, raw_response: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info("Parsing plant unit topology response")
        parse_result = parse_json_with_recovery(raw_response, expert_type=self.expert_type)
        if not parse_result.success or parse_result.data is None:
            return {"edges": [], "warnings": parse_result.warnings}

        data = parse_result.data
        warnings = parse_result.warnings.copy()
        edges: list[PlantUnitEdge] = []

        for unit_data in data.get("units", data.get("plant_unit", [])):
            if not isinstance(unit_data, dict):
                continue
            unit_id = str(unit_data.get("id", ""))
            if not unit_id:
                continue
            outlet_data = (
                unit_data.get("product_outlets")
                or unit_data.get("product_materials")
                or unit_data.get("output_materials")
                or unit_data.get("products")
                or []
            )
            try:
                edges.extend(_parse_edges_from_outlets(unit_id, outlet_data, method="vlm"))
            except Exception as exc:
                warnings.append(f"Failed to parse edges for unit '{unit_id}': {exc}")

        if parse_result.recovery_level > 0:
            warnings.append(f"JSON recovery level: {parse_result.recovery_level}")

        return {
            "drawing_id": data.get("drawing_id", "plant_unit_drawing_1"),
            "drawing_name": data.get("drawing_name", ""),
            "edges": [e.model_dump(mode="json") for e in edges],
            "topology_source": "vlm",
            "warnings": warnings + data.get("warnings", []),
            "recovery_level": parse_result.recovery_level,
        }


class PlantUnitTopologyExpertOneByOne(PlantUnitTopologyExpert):
    """Extract plant-unit topology by focusing each VLM call on one unit.

    Each ``analyze()`` call processes a single unit specified via
    ``context["current_unit"]``.  The caller is responsible for iterating
    over all units and merging per-unit results with
    :meth:`_merge_edges`.
    """

    expert_type = "plant_unit_topology_one_by_one"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        enable_preprocessing: bool = False,
        prompt_version: Optional[str] = None,
        client: Optional[VisionAPIClient] = None,
    ) -> None:
        super().__init__(
            settings=settings,
            enable_preprocessing=enable_preprocessing,
            prompt_version=prompt_version,
            client=client,
        )
        self._prompt_builder = get_prompt_builder(
            "plant_unit_topology_one_by_one", self._prompt_version
        )

    def _build_prompt(self, context: Optional[dict[str, Any]] = None) -> str:
        context = context if isinstance(context, dict) else {}
        prompt_context = PromptContext(
            image_size=getattr(self, "_current_image_size", None),
            extra={
                "current_unit_context": json.dumps(
                    context.get("current_unit", {}), ensure_ascii=False, indent=2
                ),
                "plant_unit_context": json.dumps(
                    context.get("plant_unit", []), ensure_ascii=False, indent=2
                ),
                "text_destination_context": json.dumps(
                    context.get("text_destinations", []), ensure_ascii=False, indent=2
                ),
                "unit_index": context.get("unit_index", ""),
                "unit_count": context.get("unit_count", ""),
            },
        )
        return cast(str, self._prompt_builder.build(prompt_context))

    def _parse(self, raw_response: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info("Parsing plant unit topology one-by-one response")
        parse_result = parse_json_with_recovery(raw_response, expert_type=self.expert_type)
        if not parse_result.success or parse_result.data is None:
            return {
                "current_unit_id": "",
                "edges": [],
                "warnings": parse_result.warnings,
            }

        data = parse_result.data
        warnings = parse_result.warnings.copy()
        current_unit_id = str(data.get("current_unit_id", ""))
        outlet_data = data.get("plant_unit_topology_one_by_one", [])

        try:
            edges = _parse_edges_from_outlets(current_unit_id, outlet_data, method="vlm")
        except Exception as exc:
            edges = []
            warnings.append(f"Failed to parse edges for unit '{current_unit_id}': {exc}")

        if parse_result.recovery_level > 0:
            warnings.append(f"JSON recovery level: {parse_result.recovery_level}")

        return {
            "current_unit_id": current_unit_id,
            "edges": [e.model_dump(mode="json") for e in edges],
            "warnings": warnings + data.get("warnings", []),
            "recovery_level": parse_result.recovery_level,
        }

    def analyze(
        self,
        image_path: str,
        context: Optional[dict[str, Any]] = None,
        loaded_image: Optional[Any] = None,
    ) -> ExpertOutput:
        context = context if isinstance(context, dict) else {}
        current_unit = context.get("current_unit")
        if not isinstance(current_unit, dict) or not current_unit:
            return ExpertOutput(
                expert_type=self.expert_type,
                success=False,
                data={},
                errors=["current_unit context is required for one-by-one topology extraction"],
            )
        return super().analyze(image_path, context=context, loaded_image=loaded_image)

    @staticmethod
    def _edge_key(edge: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(edge.get("source_node_id", "")),
            str(edge.get("target_node_id", "")),
            str(edge.get("material_name", "")),
        )

    @staticmethod
    def _merge_edges(outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge per-unit edge lists into a flat list, deduplicating by (source, target, material)."""
        merged: dict[tuple[str, str, str], dict[str, Any]] = {}
        for output in outputs:
            for edge in output.get("edges", []):
                if not isinstance(edge, dict):
                    continue
                key = PlantUnitTopologyExpertOneByOne._edge_key(edge)
                if key not in merged:
                    merged[key] = edge
        return list(merged.values())


def build_plant_unit_drawing(
    unit_result: dict[str, Any],
    topology_result: dict[str, Any],
) -> PlantUnitDrawing:
    """Assemble nodes + edges into a ``PlantUnitDrawing``."""
    nodes: list[PlantUnitNode] = []

    for unit in unit_result.get("plant_unit", []):
        if isinstance(unit, dict) and unit.get("id"):
            node = safe_model_validate(PlantUnitNode, unit)
            if node is not None:
                nodes.append(node)

    for dest in unit_result.get("text_destinations", []):
        if isinstance(dest, dict) and dest.get("id"):
            node = safe_model_validate(PlantUnitNode, dest)
            if node is not None:
                nodes.append(node)

    edges: list[PlantUnitEdge] = []
    for edge_data in topology_result.get("edges", []):
        if isinstance(edge_data, dict):
            edge = safe_model_validate(PlantUnitEdge, edge_data, required_fields={"source_node_id", "target_node_id"})
            if edge is not None:
                edges.append(edge)

    drawing = PlantUnitDrawing(
        drawing_id=unit_result.get("drawing_id")
        or topology_result.get("drawing_id")
        or "plant_unit_drawing_1",
        drawing_name=unit_result.get("drawing_name") or topology_result.get("drawing_name", ""),
        nodes=nodes,
        edges=edges,
        metadata={
            "unit_warnings": unit_result.get("warnings", []),
            "topology_warnings": topology_result.get("warnings", []),
            "topology_source": topology_result.get("topology_source", ""),
        },
    )
    return drawing
