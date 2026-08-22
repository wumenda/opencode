"""
DrawingInfoExpert - VLM expert for extracting drawing archive information from PFD title block
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from src.agent.experts.core.base import BaseExpert
from src.agent.prompts import get_prompt_builder, PromptContext
from src.core.models import DrawingInfo

if TYPE_CHECKING:
    from src.agent.preprocessor import ExpertImagePreprocessor
    from src.core import Settings, VisionAPIClient


class DrawingInfoExpert(BaseExpert):
    """Expert for extracting drawing archive information from PFD title block (图注).

    Extracts: drawing_id, drawing_name, drawing_number, revision, project, unit
    from the title block area typically located at the bottom-right corner of PFD drawings.

    输出数据模型为 DrawingInfo，与 PFDDrawing 的元信息字段对齐。
    """

    expert_type = "drawing_info"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        process_description: str = "",
        client: Optional[VisionAPIClient] = None,
        preprocessor: Optional[ExpertImagePreprocessor] = None,
    ) -> None:
        super().__init__(settings, client=client, preprocessor=preprocessor)
        self.process_description = process_description
        self._prompt_builder = get_prompt_builder("drawing_info", self._prompt_version)

    def _build_prompt(self, context: Optional[dict[str, Any]] = None) -> str:
        prompt_context = PromptContext(
            process_description=self.process_description or "未提供工艺流程说明",
            image_size=getattr(self, "_current_image_size", None),
        )
        return self._prompt_builder.build(prompt_context)

    def _extract(self, image_path: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info(f"Extracting drawing info from: {image_path}")
        result = self._call_vlm(image_path, context)
        result["image_path"] = image_path
        return result

    def _parse(self, raw_response: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info("Parsing drawing info response")
        parse_result = self._parse_json_with_recovery(raw_response)

        if not parse_result.success:
            self.logger.warning(f"Failed to parse JSON: {parse_result.warnings}")
            return {
                "drawing_info": DrawingInfo().model_dump(),
                "warnings": parse_result.warnings,
            }

        result_json = parse_result.data
        raw_info = result_json.get("drawing_info", {})

        if not isinstance(raw_info, dict):
            raw_info = {}

        drawing_info = DrawingInfo(
            drawing_id=str(raw_info.get("drawing_id", "")).strip(),
            drawing_name=str(raw_info.get("drawing_name", "")).strip(),
            drawing_number=str(raw_info.get("drawing_number", "")).strip(),
            revision=str(raw_info.get("revision", "")).strip(),
            project=str(raw_info.get("project", "")).strip(),
            unit=str(raw_info.get("unit", "")).strip(),
        )

        warnings = parse_result.warnings.copy()
        if parse_result.recovery_level > 0:
            warnings.append(f"JSON recovery level: {parse_result.recovery_level}")

        return {
            "drawing_info": drawing_info.model_dump(),
            "warnings": warnings,
            "recovery_level": parse_result.recovery_level,
        }
