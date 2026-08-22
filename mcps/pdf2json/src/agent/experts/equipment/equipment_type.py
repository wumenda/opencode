"""EquipmentTypeExpert - VLM expert that classifies an equipment assembly drawing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, cast

from src.agent.experts.core.base import BaseExpert
from src.agent.prompts import PromptContext, get_prompt_builder
from src.core.models import AssemblyDrawingType

if TYPE_CHECKING:
    from src.agent.preprocessor import ExpertImagePreprocessor
    from src.core import Settings, VisionAPIClient


class EquipmentTypeExpert(BaseExpert):
    """Classify an equipment assembly drawing as column_tray / column_packed / reactor / unknown."""

    expert_type = "equipment_type"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[VisionAPIClient] = None,
        preprocessor: Optional[ExpertImagePreprocessor] = None,
    ) -> None:
        super().__init__(settings, client=client, preprocessor=preprocessor)
        self._prompt_builder = get_prompt_builder("equipment_type", self._prompt_version)

    def _build_prompt(self, context: Optional[dict[str, Any]] = None) -> str:
        prompt_context = PromptContext(
            image_size=getattr(self, "_current_image_size", None),
            extra=context or {},
        )
        return cast(str, self._prompt_builder.build(prompt_context))

    def _extract(self, image_path: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info(f"Classifying equipment type from: {image_path}")
        result = self._call_vlm(image_path, context)
        result["image_path"] = image_path
        return result

    def _parse(self, raw_response: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info("Parsing equipment type response")
        parse_result = self._parse_json_with_recovery(raw_response)

        warnings = parse_result.warnings.copy()
        if not parse_result.success:
            return self._fallback(warnings, parse_result.recovery_level)

        data = parse_result.data if isinstance(parse_result.data, dict) else {}
        equipment_type = self._normalize_equipment_type(data.get("equipment_type"))
        evidence = str(data.get("evidence", "") or "").strip()
        confidence = self._normalize_confidence(data.get("confidence"))

        if parse_result.recovery_level > 0:
            warnings.append(f"JSON recovery level: {parse_result.recovery_level}")

        if equipment_type == AssemblyDrawingType.UNKNOWN.value:
            warnings.append("equipment type could not be determined, defaulted to unknown")

        return {
            "equipment_type": equipment_type,
            "evidence": evidence,
            "confidence": confidence,
            "warnings": warnings,
            "recovery_level": parse_result.recovery_level,
        }

    def _fallback(self, warnings: list[str], recovery_level: int) -> dict[str, Any]:
        warnings.append("equipment type parsing failed, defaulted to unknown")
        return {
            "equipment_type": AssemblyDrawingType.UNKNOWN.value,
            "evidence": "",
            "confidence": 0.0,
            "warnings": warnings,
            "recovery_level": recovery_level,
        }

    @staticmethod
    def _normalize_equipment_type(value: Any) -> str:
        if not isinstance(value, str):
            return AssemblyDrawingType.UNKNOWN.value
        normalized = value.strip().lower()
        for member in AssemblyDrawingType:
            if member.value == normalized:
                return member.value
        return AssemblyDrawingType.UNKNOWN.value

    @staticmethod
    def _normalize_confidence(value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0
