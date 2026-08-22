"""PlantUnitExpert - whole-plant unit node and product list extraction."""

from __future__ import annotations

from typing import Any, Optional, cast

from src.agent.experts.core.base import BaseExpert
from src.agent.prompts import PromptContext, get_prompt_builder
from src.core import Settings, VisionAPIClient
from src.core.models import PlantUnitNode, safe_model_validate

from .plant_unit_parsers import (
    _bbox_from_pixels_or_none,
    _parse_feed_inlets,
    _parse_feed_requirements,
    _parse_product_outlets,
    _tuple_or_none,
)


class PlantUnitExpert(BaseExpert):
    """Extract whole-plant unit nodes and their product lists."""

    expert_type = "plant_unit"
    _DEFAULT_PLANT_UNIT_TYPE = "plant_unit_general"
    _SUPPORTED_PLANT_UNIT_TYPES = frozenset({"plant_unit_general", "plant_unit_dense"})

    def __init__(
        self,
        settings: Optional[Settings] = None,
        enable_preprocessing: bool = False,
        prompt_version: Optional[str] = None,
        client: Optional[VisionAPIClient] = None,
        plant_unit_type: str = _DEFAULT_PLANT_UNIT_TYPE,
    ) -> None:
        super().__init__(
            settings=settings,
            enable_preprocessing=enable_preprocessing,
            prompt_version=prompt_version,
            client=client,
        )
        if plant_unit_type not in self._SUPPORTED_PLANT_UNIT_TYPES:
            raise ValueError(
                f"Unsupported plant_unit_type '{plant_unit_type}'. "
                f"Expected one of: {sorted(self._SUPPORTED_PLANT_UNIT_TYPES)}"
            )
        self.plant_unit_type = plant_unit_type
        self._prompt_builder = get_prompt_builder(plant_unit_type, self._prompt_version)

    def _extract(self, image_path: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info(f"Extracting plant units from: {image_path}")
        return cast(dict[str, Any], self._call_vlm(image_path, context=context))

    def _build_prompt(self, context: Optional[dict[str, Any]] = None) -> str:
        prompt_context = PromptContext(image_size=getattr(self, "_current_image_size", None))
        return cast(str, self._prompt_builder.build(prompt_context))

    def _parse(self, raw_response: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info("Parsing plant unit response")
        parse_result = self._parse_json_with_recovery(raw_response)
        if not parse_result.success or parse_result.data is None:
            return {"plant_unit": [], "warnings": parse_result.warnings}

        data = parse_result.data
        units: list[PlantUnitNode] = []
        text_destinations: list[PlantUnitNode] = []
        warnings = parse_result.warnings.copy()
        image_size = getattr(self, "_current_image_size", None)

        for idx, unit_data in enumerate(data.get("plant_unit", []), start=1):
            if not isinstance(unit_data, dict):
                warnings.append(f"Skipping malformed plant unit at index {idx}")
                continue
            unit_id = str(unit_data.get("id") or f"unit_{idx:03d}")
            try:
                unit = safe_model_validate(PlantUnitNode, {
                    "id": unit_id,
                    "node_type": str(unit_data.get("node_type") or "plant_unit"),
                    "name": str(unit_data.get("name") or unit_id),
                    "unit_name": str(unit_data.get("unit_name") or ""),
                    "unit_trains": [str(train) for train in unit_data.get("unit_trains", []) if str(train).strip()],
                    "feeds": [str(feed) for feed in unit_data.get("feeds", []) if not isinstance(feed, dict) and str(feed).strip()],
                    "feed_inlets": _parse_feed_inlets(unit_data),
                    "feed_requirements": _parse_feed_requirements(unit_data),
                    "products": [str(product) for product in unit_data.get("products", []) if not isinstance(product, dict) and str(product).strip()],
                    "product_outlets": _parse_product_outlets(unit_data),
                    "bbox": (_bbox_from_pixels_or_none(unit_data.get("bbox_pixels") or unit_data.get("bbox_px"), image_size) or _tuple_or_none(unit_data.get("bbox"), 4)),
                    "position": _tuple_or_none(unit_data.get("position"), 2),
                    "aliases": [str(alias) for alias in unit_data.get("aliases", []) if str(alias).strip()],
                    "metadata": (unit_data.get("metadata", {}) if isinstance(unit_data.get("metadata", {}), dict) else {}),
                }, logger=self.logger)
                if unit is not None:
                    units.append(unit)
            except Exception as exc:
                warnings.append(f"Failed to parse plant unit '{unit_id}': {exc}")

        for idx, dest_data in enumerate(data.get("text_destinations", []), start=1):
            if not isinstance(dest_data, dict):
                warnings.append(f"Skipping malformed text destination at index {idx}")
                continue
            dest_id = str(dest_data.get("id") or f"dest_{idx:03d}")
            try:
                dest = safe_model_validate(PlantUnitNode, {
                    "id": dest_id,
                    "node_type": "text_destination",
                    "name": str(dest_data.get("name") or dest_id),
                    "bbox": (_bbox_from_pixels_or_none(dest_data.get("bbox_pixels") or dest_data.get("bbox_px"), image_size) or _tuple_or_none(dest_data.get("bbox"), 4)),
                    "position": _tuple_or_none(dest_data.get("position"), 2),
                }, logger=self.logger)
                if dest is not None:
                    text_destinations.append(dest)
            except Exception as exc:
                warnings.append(f"Failed to parse text destination '{dest_id}': {exc}")

        if parse_result.recovery_level > 0:
            warnings.append(f"JSON recovery level: {parse_result.recovery_level}")

        return {
            "drawing_id": data.get("drawing_id", "plant_unit_drawing_1"),
            "drawing_name": data.get("drawing_name", ""),
            "plant_unit": [unit.model_dump(mode="json") for unit in units],
            "text_destinations": [dest.model_dump(mode="json") for dest in text_destinations],
            "warnings": warnings + data.get("warnings", []),
            "recovery_level": parse_result.recovery_level,
        }
