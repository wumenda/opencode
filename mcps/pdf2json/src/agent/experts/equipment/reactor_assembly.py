"""
ReactorAssemblyExpert - VLM expert for reactor assembly drawing design data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, cast

from src.agent.experts.core.base import BaseExpert
from src.agent.prompts import PromptContext, get_prompt_builder
from src.core.models import Reactor, safe_model_validate

if TYPE_CHECKING:
    from src.agent.preprocessor import ExpertImagePreprocessor
    from src.core import Settings, VisionAPIClient


class ReactorAssemblyExpert(BaseExpert):
    """Extract reactor design data from equipment assembly drawings."""

    expert_type = "reactor_assembly"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[VisionAPIClient] = None,
        preprocessor: Optional[ExpertImagePreprocessor] = None,
    ) -> None:
        super().__init__(settings, client=client, preprocessor=preprocessor)
        self._prompt_builder = get_prompt_builder("reactor_assembly", self._prompt_version)

    def _build_prompt(self, context: Optional[dict[str, Any]] = None) -> str:
        prompt_context = PromptContext(
            image_size=getattr(self, "_current_image_size", None),
            extra=context or {},
        )
        return self._prompt_builder.build(prompt_context)

    def _extract(self, image_path: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info(f"Extracting reactor assembly design data from: {image_path}")
        result = self._call_vlm(image_path, context)
        result["image_path"] = image_path
        return result

    def _parse(self, raw_response: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info("Parsing reactor assembly response")
        parse_result = self._parse_json_with_recovery(raw_response)

        warnings = parse_result.warnings.copy()
        if not parse_result.success:
            return {
                "reactor_design": self._empty_reactor(context),
                "warnings": warnings,
            }

        raw_reactor = self._select_reactor_payload(parse_result.data)
        raw_reactor = self._remap_legacy_fields(raw_reactor, context)

        reactor = safe_model_validate(Reactor, raw_reactor)
        if reactor is None:
            warnings.append("reactor schema normalization failed, using empty model")
            reactor = Reactor(source_image_id=self._context_id(context))

        if parse_result.recovery_level > 0:
            warnings.append(f"JSON recovery level: {parse_result.recovery_level}")

        payload = reactor.to_dict()
        payload["warnings"] = self._merge_warnings(payload.get("warnings", []), warnings)

        return {
            "reactor_design": payload,
            "warnings": warnings,
            "recovery_level": parse_result.recovery_level,
        }

    @classmethod
    def _select_reactor_payload(cls, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {}
        for key in ("reactor_design", "reactor", "data"):
            value = data.get(key)
            if isinstance(value, dict):
                return value.copy()
        return data.copy() if isinstance(data, dict) else {}

    @classmethod
    def _remap_legacy_fields(
        cls,
        raw: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        raw = raw.copy()

        context_id = cls._context_id(context)
        if context_id and not raw.get("source_image_id"):
            raw["source_image_id"] = context_id
        if "id" in raw and "source_image_id" not in raw:
            raw["source_image_id"] = str(raw.pop("id")).strip()
        elif "id" in raw:
            raw.pop("id", None)

        info: dict[str, Any] = raw.get("info", {})
        if not isinstance(info, dict):
            info = {}

        for legacy_key, target_key in (
            ("tag", "equipment_tag"),
            ("name", "equipment_name"),
        ):
            if legacy_key in raw and target_key not in info:
                info[target_key] = raw.pop(legacy_key)

        if info:
            raw["info"] = info

        nozzles = raw.get("nozzles")
        if nozzles is None:
            for alt_key in ("ports", "nozzle_list"):
                alt = raw.pop(alt_key, None)
                if isinstance(alt, list):
                    nozzles = alt
                    break
        if isinstance(nozzles, list):
            raw["nozzles"] = [n for n in nozzles if isinstance(n, dict)]
        elif "nozzles" not in raw:
            raw["nozzles"] = []

        return raw

    @classmethod
    def _empty_reactor(cls, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            Reactor(source_image_id=cls._context_id(context)).to_dict(),
        )

    @staticmethod
    def _context_id(context: Optional[dict[str, Any]]) -> str:
        if not context:
            return ""
        value = context.get("reactor_id") or context.get("source_image_id") or context.get("id")
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



