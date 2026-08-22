"""ColumnAssemblyExpert - VLM expert for column assembly drawings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, cast

from pydantic import TypeAdapter

from src.agent.experts.core.base import BaseExpert
from src.agent.prompts import PromptContext, get_prompt_builder
from src.core.models import Column

if TYPE_CHECKING:
    from src.agent.preprocessor import ExpertImagePreprocessor
    from src.core import Settings, VisionAPIClient


class ColumnAssemblyExpert(BaseExpert):
    """Extract column internals and nozzle placement from assembly drawings."""

    expert_type = "column_assembly"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[VisionAPIClient] = None,
        preprocessor: Optional[ExpertImagePreprocessor] = None,
    ) -> None:
        super().__init__(settings, client=client, preprocessor=preprocessor)
        self._prompt_builder = get_prompt_builder(
            "column_assembly", self._prompt_version
        )

    @staticmethod
    def _resolve_column_type(context: Optional[dict[str, Any]]) -> str:
        if not context:
            return ""
        ct = context.get("column_type", "")
        if isinstance(ct, str):
            return ct.strip().lower()
        return ""

    def _build_prompt(self, context: Optional[dict[str, Any]] = None) -> str:
        column_type = self._resolve_column_type(context)
        if column_type == "tray":
            builder = get_prompt_builder("column_assembly", "v1")
        elif column_type == "packed":
            builder = get_prompt_builder("column_assembly", "v2")
        else:
            builder = self._prompt_builder

        prompt_context = PromptContext(
            image_size=getattr(self, "_current_image_size", None),
            extra=context or {},
        )
        return cast(str, builder.build(prompt_context))

    def _extract(self, image_path: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info(f"Extracting distillation column assembly data from: {image_path}")
        result = self._call_vlm(image_path, context)
        result["image_path"] = image_path
        return cast(dict[str, Any], result)

    def _parse(self, raw_response: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info("Parsing column assembly response")
        parse_result = self._parse_json_with_recovery(raw_response)

        warnings = parse_result.warnings.copy()
        if not parse_result.success:
            return {
                "distillation_column": self._empty_column(context),
                "warnings": warnings,
            }

        raw_column = self._select_column_payload(parse_result.data)
        if not raw_column.get("source_image_id"):
            source_id = self._context_id(context)
            if source_id:
                raw_column["source_image_id"] = source_id

        column_type = self._resolve_column_type(context)
        try:
            column = self._validate_column(raw_column, column_type)
        except Exception as exc:
            warnings.append(f"distillation column schema normalization failed: {exc}")
            column = Column(source_image_id=self._context_id(context))

        if parse_result.recovery_level > 0:
            warnings.append(f"JSON recovery level: {parse_result.recovery_level}")

        payload = column.to_dict()
        payload["warnings"] = self._merge_warnings(payload.get("warnings", []), warnings)

        return {
            "distillation_column": payload,
            "warnings": warnings,
            "recovery_level": parse_result.recovery_level,
        }

    @classmethod
    def _validate_column(cls, raw_column: dict[str, Any], column_type: str):
        if column_type == "tray":
            raw_column.setdefault("column_type", "tray")
        elif column_type == "packed":
            raw_column.setdefault("column_type", "packed")
        return TypeAdapter(Column).validate_python(raw_column)

    @classmethod
    def _select_column_payload(cls, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {}
        for key in ("distillation_column", "column", "data"):
            value = data.get(key)
            if isinstance(value, dict):
                return value.copy()
        return data.copy()

    @classmethod
    def _empty_column(cls, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            Column(source_image_id=cls._context_id(context)).to_dict(),
        )

    @staticmethod
    def _context_id(context: Optional[dict[str, Any]]) -> str:
        if not context:
            return ""
        value = context.get("column_id") or context.get("source_image_id") or context.get("id")
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _merge_warnings(existing: list[Any], new_items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in [*existing, *new_items]:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result
