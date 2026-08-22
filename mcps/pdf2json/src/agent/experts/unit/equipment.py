"""
Equipment Expert - V1 version
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from src.agent.experts.core.base import BaseExpert
from src.agent.prompts import get_prompt_builder, PromptContext
from src.core.models import (
    PFDEquipmentNode as EquipmentNode,
    EquipmentType,
    Port,
    PortDirection,
    PortCategory,
    PortOrientation,
)

if TYPE_CHECKING:
    from src.agent.preprocessor import ExpertImagePreprocessor
    from src.core import Settings, VisionAPIClient


class EquipmentExpert(BaseExpert):
    """Expert for identifying equipment with ports using pfd_model."""

    expert_type = "equipment"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        process_description: str = "",
        enable_preprocessing: bool = True,
        client: Optional[VisionAPIClient] = None,
        preprocessor: Optional[ExpertImagePreprocessor] = None,
    ) -> None:
        super().__init__(
            settings,
            enable_preprocessing=enable_preprocessing,
            client=client,
            preprocessor=preprocessor,
        )
        self.process_description = process_description
        self._prompt_builder = get_prompt_builder("equipment", self._prompt_version)

    @staticmethod
    def _parse_port_direction(value: Any) -> PortDirection:
        if isinstance(value, PortDirection):
            return value
        normalized = str(value or PortDirection.UNKNOWN.value).strip().lower()
        try:
            return PortDirection(normalized)
        except Exception:
            return PortDirection.UNKNOWN

    @staticmethod
    def _parse_port_category(value: Any) -> PortCategory:
        if isinstance(value, PortCategory):
            return value
        normalized = str(value or PortCategory.PROCESS.value).strip().lower()
        try:
            return PortCategory(normalized)
        except Exception:
            return PortCategory.PROCESS

    @staticmethod
    def _parse_port_orientation(value: Any) -> PortOrientation:
        if isinstance(value, PortOrientation):
            return value
        normalized = str(value or PortOrientation.UNKNOWN.value).strip().lower()
        try:
            return PortOrientation(normalized)
        except Exception:
            return PortOrientation.UNKNOWN

    def _extract(self, image_path: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info(f"Extracting equipment from: {image_path}")
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
        """Parse raw response into structured equipment data."""

        self.logger.info("Parsing equipment response")
        parse_result = self._parse_json_with_recovery(raw_response)

        if not parse_result.success:
            self.logger.warning(f"Failed to parse JSON: {parse_result.warnings}")
            return {"equipment": [], "warnings": parse_result.warnings}

        result_json = parse_result.data
        equipment_list: list[EquipmentNode] = []

        for eq_data in result_json.get("equipment", []):
            try:
                equipment_id = str(eq_data.get("id") or "")
                ports: list[Port] = []

                for port_data in eq_data.get("ports", []):
                    if not isinstance(port_data, dict):
                        self.logger.warning(
                            f"Skipping malformed port on {equipment_id}: {port_data}"
                        )
                        continue

                    direction = self._parse_port_direction(port_data.get("direction"))

                    port = Port(
                        id=str(port_data.get("id") or ""),
                        direction=direction,
                        category=self._parse_port_category(port_data.get("category")),
                        label=str(port_data.get("label") or ""),
                        position=(
                            tuple(port_data.get("position")) if port_data.get("position") else None
                        ),
                        parent_node_id=str(port_data.get("parent_node_id") or equipment_id or ""),
                        orientation=self._parse_port_orientation(
                            port_data.get("orientation")
                        ),
                        channel=str(port_data.get("channel", "") or ""),
                    )
                    ports.append(port)

                equipment_type_raw = eq_data.get("equipment_type", EquipmentType.OTHER)
                try:
                    equipment_type = EquipmentType(equipment_type_raw)
                except Exception:
                    equipment_type = EquipmentType.OTHER

                equip = EquipmentNode(
                    id=str(eq_data.get("id") or ""),
                    name=str(eq_data.get("name") or ""),
                    equipment_type=equipment_type,
                    tag=str(eq_data.get("tag") or ""),
                    ports=ports,
                    position=tuple(eq_data.get("position")) if eq_data.get("position") else None,
                    bbox=tuple(eq_data.get("bbox")) if eq_data.get("bbox") else None,
                )
                equipment_list.append(equip)
            except Exception as e:
                self.logger.warning(f"Failed to parse equipment: {e}")

        warnings = parse_result.warnings.copy()
        if parse_result.recovery_level > 0:
            warnings.append(f"JSON recovery level: {parse_result.recovery_level}")

        return {
            "equipment": [e.model_dump() for e in equipment_list],
            "warnings": warnings,
            "recovery_level": parse_result.recovery_level,
        }
