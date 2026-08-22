"""组分表信息提取专家。

从化工工艺图纸图片中识别组分表 / 物料平衡表 / 流股组成表，
输出 :class:`CompositionTable` 结构化数据（components + streams）。
图像输入，调用 VLM。
"""

from __future__ import annotations

from typing import Any, Optional

from src.agent.experts.core.base import BaseExpert
from src.agent.prompts import PromptContext, get_prompt_builder
from src.core import Settings, VisionAPIClient
from src.core.io.json_utils import parse_json_with_recovery
from src.core.models.unit.composition_table import (
    Component,
    CompositionEntry,
    CompositionTable,
    Quantity,
    Stream,
)


class CompositionTableExpert(BaseExpert):
    """从图片中提取组分表信息。

    输入为图纸图片路径，输出为 :class:`CompositionTable` 的 dict 形式，
    包含 components（组分定义）与 streams（物流组成）。
    """

    expert_type = "composition_table"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        process_description: str = "",
        enable_preprocessing: bool = False,
        prompt_version: Optional[str] = None,
        client: Optional[VisionAPIClient] = None,
    ) -> None:
        super().__init__(
            settings,
            enable_preprocessing=enable_preprocessing,
            prompt_version=prompt_version,
            client=client,
        )
        self.process_description = process_description
        self._prompt_builder = get_prompt_builder(
            "composition_table", self._prompt_version
        )

    def _build_prompt(self, context: Optional[dict[str, Any]] = None) -> str:
        prompt_context = PromptContext(
            process_description=self.process_description or "未提供工艺流程说明",
            image_size=getattr(self, "_current_image_size", None),
        )
        return self._prompt_builder.build(prompt_context)

    def _extract(
        self, image_path: str, context: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """调用 VLM 提取组分表信息。"""
        self.logger.info(f"Extracting composition table from: {image_path}")
        result = self._call_vlm(image_path, context)
        result["image_path"] = image_path
        return result

    def _parse(
        self, raw_response: str, context: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """将 VLM 原始响应解析为 CompositionTable 结构化数据。"""
        self.logger.info("Parsing composition table response")

        parse_result = parse_json_with_recovery(raw_response, expert_type=self.expert_type)
        warnings = parse_result.warnings.copy()
        if parse_result.recovery_level > 0:
            warnings.append(f"JSON recovery level: {parse_result.recovery_level}")

        if not parse_result.success or parse_result.data is None:
            return CompositionTable(
                warnings=warnings + ["Failed to parse JSON response"]
            ).to_dict()

        data = parse_result.data
        try:
            table = self._build_composition_table(data, warnings)
            return table.to_dict()
        except Exception as e:
            self.logger.warning(f"Failed to validate CompositionTable: {e}")
            return CompositionTable(
                components=self._safe_components(data.get("components", [])),
                streams=self._safe_streams(data.get("streams", [])),
                warnings=warnings + [f"Model validation failed: {e}"],
            ).to_dict()

    # ------------------------------------------------------------------
    # 构建辅助
    # ------------------------------------------------------------------

    def _build_composition_table(
        self, data: dict[str, Any], warnings: list[str]
    ) -> CompositionTable:
        components = self._safe_components(data.get("components", []))
        streams = self._safe_streams(data.get("streams", []))
        return CompositionTable(
            components=components,
            streams=streams,
            warnings=warnings + (data.get("warnings", []) or []),
        )

    @staticmethod
    def _safe_components(raw: Any) -> list[Component]:
        if not isinstance(raw, list):
            return []
        components: list[Component] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            mw = item.get("molecular_weight")
            try:
                mw_val = float(mw) if mw is not None else None
            except (TypeError, ValueError):
                mw_val = None
            components.append(Component(name=name, molecular_weight=mw_val))
        return components

    @staticmethod
    def _safe_streams(raw: Any) -> list[Stream]:
        if not isinstance(raw, list):
            return []
        streams: list[Stream] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            streams.append(
                Stream(
                    stream_id=str(item.get("stream_id", "")).strip(),
                    flow_rate=CompositionTableExpert._safe_quantity(item.get("flow_rate")),
                    composition=CompositionTableExpert._safe_composition(
                        item.get("composition", [])
                    ),
                    temperature=CompositionTableExpert._safe_quantity(
                        item.get("temperature")
                    ),
                    pressure=CompositionTableExpert._safe_quantity(item.get("pressure")),
                    phase=str(item.get("phase", "")).strip(),
                )
            )
        return streams

    @staticmethod
    def _safe_quantity(raw: Any) -> Quantity:
        if isinstance(raw, dict):
            value = raw.get("value")
            try:
                value_val = float(value) if value is not None else None
            except (TypeError, ValueError):
                value_val = None
            return Quantity(value=value_val, unit=str(raw.get("unit", "")).strip())
        return Quantity()

    @staticmethod
    def _safe_composition(raw: Any) -> list[CompositionEntry]:
        if not isinstance(raw, list):
            return []
        entries: list[CompositionEntry] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            component = str(item.get("component", "")).strip()
            if not component:
                continue
            entries.append(
                CompositionEntry(
                    component=component,
                    mole_fraction=CompositionTableExpert._safe_fraction(
                        item.get("mole_fraction")
                    ),
                    mass_fraction=CompositionTableExpert._safe_fraction(
                        item.get("mass_fraction")
                    ),
                )
            )
        return entries

    @staticmethod
    def _safe_fraction(raw: Any) -> Optional[float]:
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
