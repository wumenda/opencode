"""PFD 塔与反应器回流结构分析专家。

从化工 PFD 图纸图片中识别所有塔和反应器，判断是否存在回流结构，
并提取塔回流详情（冷凝器/再沸器/回流量）与塔/反应器操作条件。
图像输入，调用 VLM。
"""

from __future__ import annotations

from typing import Any, Optional

from src.agent.experts.core.base import BaseExpert
from src.agent.prompts import PromptContext, get_prompt_builder
from src.core import Settings, VisionAPIClient
from src.core.io.json_utils import parse_json_with_recovery
from src.core.models.unit.pfd_reflux import (
    PFDRefluxAnalysis,
    Quantity,
    ReactorInfo,
    ReactorOperatingConditions,
    RefluxStructure,
    TowerInfo,
    TowerOperatingConditions,
    TowerRefluxDetail,
)


class PFDRefluxExpert(BaseExpert):
    """从 PFD 图片中提取塔与反应器回流结构信息。

    输入为 PFD 图纸图片路径，输出为 :class:`PFDRefluxAnalysis` 的 dict 形式，
    包含 towers（塔信息列表）与 reactors（反应器信息列表）。
    """

    expert_type = "pfd_reflux"

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
            "pfd_reflux", self._prompt_version
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
        """调用 VLM 提取塔与反应器回流结构信息。"""
        self.logger.info(f"Extracting PFD reflux analysis from: {image_path}")
        result = self._call_vlm(image_path, context)
        result["image_path"] = image_path
        return result

    def _parse(
        self, raw_response: str, context: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """将 VLM 原始响应解析为 PFDRefluxAnalysis 结构化数据。"""
        self.logger.info("Parsing PFD reflux analysis response")

        parse_result = parse_json_with_recovery(raw_response, expert_type=self.expert_type)
        warnings = parse_result.warnings.copy()
        if parse_result.recovery_level > 0:
            warnings.append(f"JSON recovery level: {parse_result.recovery_level}")

        if not parse_result.success or parse_result.data is None:
            return PFDRefluxAnalysis(
                warnings=warnings + ["Failed to parse JSON response"]
            ).to_dict()

        data = parse_result.data
        try:
            analysis = self._build_analysis(data, warnings)
            return analysis.to_dict()
        except Exception as e:
            self.logger.warning(f"Failed to validate PFDRefluxAnalysis: {e}")
            return PFDRefluxAnalysis(
                towers=self._safe_towers(data.get("towers", [])),
                reactors=self._safe_reactors(data.get("reactors", [])),
                warnings=warnings + [f"Model validation failed: {e}"],
            ).to_dict()

    # ------------------------------------------------------------------
    # 构建辅助
    # ------------------------------------------------------------------

    def _build_analysis(
        self, data: dict[str, Any], warnings: list[str]
    ) -> PFDRefluxAnalysis:
        towers = self._safe_towers(data.get("towers", []))
        reactors = self._safe_reactors(data.get("reactors", []))
        return PFDRefluxAnalysis(
            towers=towers,
            reactors=reactors,
            warnings=warnings + (data.get("warnings", []) or []),
        )

    @staticmethod
    def _safe_towers(raw: Any) -> list[TowerInfo]:
        if not isinstance(raw, list):
            return []
        towers: list[TowerInfo] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            tag = str(item.get("tag", "")).strip()
            if not tag:
                continue
            towers.append(
                TowerInfo(
                    tag=tag,
                    name=str(item.get("name", "")).strip(),
                    reflux_structure=PFDRefluxExpert._safe_reflux_structure(
                        item.get("reflux_structure")
                    ),
                    reflux_detail=PFDRefluxExpert._safe_reflux_detail(
                        item.get("reflux_detail"),
                        item.get("reflux_structure"),
                    ),
                    operating_conditions=PFDRefluxExpert._safe_tower_op_conditions(
                        item.get("operating_conditions")
                    ),
                )
            )
        return towers

    @staticmethod
    def _safe_reactors(raw: Any) -> list[ReactorInfo]:
        if not isinstance(raw, list):
            return []
        reactors: list[ReactorInfo] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            tag = str(item.get("tag", "")).strip()
            if not tag:
                continue
            reactors.append(
                ReactorInfo(
                    tag=tag,
                    name=str(item.get("name", "")).strip(),
                    reflux_structure=PFDRefluxExpert._safe_reflux_structure(
                        item.get("reflux_structure")
                    ),
                    operating_conditions=PFDRefluxExpert._safe_reactor_op_conditions(
                        item.get("operating_conditions")
                    ),
                )
            )
        return reactors

    @staticmethod
    def _safe_reflux_structure(raw: Any) -> RefluxStructure:
        if not isinstance(raw, dict):
            return RefluxStructure()
        return RefluxStructure(
            has_reflux=bool(raw.get("has_reflux", False)),
            reflux_type=str(raw.get("reflux_type", "none") or "none").strip(),
            description=str(raw.get("description", "")).strip(),
        )

    @staticmethod
    def _safe_reflux_detail(
        raw: Any, reflux_structure_raw: Any
    ) -> Optional[TowerRefluxDetail]:
        """回流详情仅在 has_reflux=True 时保留，否则强制 None。"""
        has_reflux = False
        if isinstance(reflux_structure_raw, dict):
            has_reflux = bool(reflux_structure_raw.get("has_reflux", False))
        if not has_reflux:
            return None
        if not isinstance(raw, dict):
            return TowerRefluxDetail()
        return TowerRefluxDetail(
            has_top_condenser=PFDRefluxExpert._safe_bool(raw.get("has_top_condenser")),
            has_bottom_reboiler=PFDRefluxExpert._safe_bool(
                raw.get("has_bottom_reboiler")
            ),
            top_condenser_tag=str(raw.get("top_condenser_tag", "")).strip(),
            bottom_reboiler_tag=str(raw.get("bottom_reboiler_tag", "")).strip(),
            reflux_flow_rate=PFDRefluxExpert._safe_quantity(
                raw.get("reflux_flow_rate")
            ),
        )

    @staticmethod
    def _safe_tower_op_conditions(raw: Any) -> TowerOperatingConditions:
        if not isinstance(raw, dict):
            return TowerOperatingConditions()
        return TowerOperatingConditions(
            top_temperature=PFDRefluxExpert._safe_quantity(raw.get("top_temperature")),
            top_pressure=PFDRefluxExpert._safe_quantity(raw.get("top_pressure")),
            bottom_temperature=PFDRefluxExpert._safe_quantity(
                raw.get("bottom_temperature")
            ),
            bottom_pressure=PFDRefluxExpert._safe_quantity(raw.get("bottom_pressure")),
        )

    @staticmethod
    def _safe_reactor_op_conditions(raw: Any) -> ReactorOperatingConditions:
        if not isinstance(raw, dict):
            return ReactorOperatingConditions()
        return ReactorOperatingConditions(
            temperature=PFDRefluxExpert._safe_quantity(raw.get("temperature")),
            pressure=PFDRefluxExpert._safe_quantity(raw.get("pressure")),
        )

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
    def _safe_bool(raw: Any) -> Optional[bool]:
        if raw is None:
            return None
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            s = raw.strip().lower()
            if s in ("true", "1", "yes"):
                return True
            if s in ("false", "0", "no"):
                return False
        return None
