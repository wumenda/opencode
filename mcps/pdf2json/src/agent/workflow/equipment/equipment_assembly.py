"""EquipmentAssemblyWorkflow — 设备装配图提取工作流。

两阶段编排：
    Phase 1: EquipmentTypeExpert 判别设备类型（column_tray / column_packed / reactor / unknown）
    Phase 2: 根据判别结果路由到对应装配提取专家
        - column_tray / column_packed → ColumnAssemblyExpert（按类型选择提示词）
        - reactor → ReactorAssemblyExpert
        - unknown → 默认走 ColumnAssemblyExpert（带告警）

替代原本需要用户手动指定设备类型的调用方式。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional

from src.agent.experts.equipment import (
    ColumnAssemblyExpert,
    EquipmentTypeExpert,
    ReactorAssemblyExpert,
)
from src.agent.models import ExpertOutput
from src.agent.workflow.core import BaseWorkflow
from src.core import get_logger
from src.core.infra.exceptions import CancelledByClientError, PFDAnalysisError

logger = get_logger(__name__)


class EquipmentAssemblyWorkflow(BaseWorkflow):
    """设备装配图提取工作流：先判类型，再路由到对应装配提取专家。"""

    workflow_name = "equipment_assembly"

    def _init_experts(self) -> None:
        self.type_expert = EquipmentTypeExpert(self.settings)
        self.column_assembly_expert = ColumnAssemblyExpert(self.settings)
        self.reactor_assembly_expert = ReactorAssemblyExpert(self.settings)

    def _log_workflow_info(self) -> None:
        logger.info("=" * 60)
        logger.info(f"Workflow: {self.workflow_name}")
        logger.info(
            f"  EquipmentType prompt version: {self.type_expert._prompt_builder.version}"
        )
        logger.info(
            f"  ColumnAssembly prompt version: {self.column_assembly_expert._prompt_builder.version}"
        )
        logger.info(
            f"  ReactorAssembly prompt version: {self.reactor_assembly_expert._prompt_builder.version}"
        )
        logger.info("-" * 60)
        logger.info(
            "Phase 1: EquipmentTypeExpert — 设备类型判别（column_tray / column_packed / reactor / unknown）"
        )
        logger.info("Phase 2: 路由到 ColumnAssemblyExpert 或 ReactorAssemblyExpert 提取装配信息")
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        image_path: str,
        equipment_id: str = "",
        equipment_type: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> dict[str, Any]:
        """提取设备装配图信息，自动判别设备类型后调用对应装配提取专家。

        Args:
            image_path: 设备装配图图片路径。
            equipment_id: 可选的设备位号/样本 id，用于上下文回填。
            equipment_type: 可选的设备类型（column_tray / column_packed /
                reactor / unknown）。传入时跳过类型判别，直接路由到对应专家。
            cancel_event: 可选的取消事件，用于客户端取消任务。

        Returns:
            dict 包含：
                - status: ``"success"`` / ``"partial"``
                - workflow / image_path / equipment_id
                - equipment_type: 判别的设备类型（column_tray / column_packed / reactor / unknown）
                - type_detection: 类型判别明细（equipment_type / evidence / confidence）
                - assembly: 装配提取结果，结构随设备类型变化：
                    - column_tray/column_packed/unknown: ``{"distillation_column": {...}}``
                    - reactor: ``{"reactor_design": {...}}``
                - warnings: 合并的告警列表
        """
        self._cancel_event = cancel_event
        self._content.send_progress_with_data(0, total=3, message="Starting equipment assembly extraction")

        # 通过 HostClient 加载图片为内存 Image（不触碰本地文件 API）
        loaded_image = self._load_image(image_path) if self._host_client else None
        image = Path(image_path)
        if loaded_image is None and not image.exists():
            raise PFDAnalysisError(f"Image file not found: {image}")

        self.logger.info("=" * 80)
        self.logger.info(f"Workflow {self.workflow_name} started")
        self.logger.info(f"Input image: {image}")
        self.logger.info(f"Equipment id: {equipment_id or '(none)'}")
        self.logger.info("=" * 80)

        context = {
            "equipment_id": equipment_id,
            "source_image_id": equipment_id,
        }

        # Phase 1: 类型判别（调用者已指定 equipment_type 时跳过自动判别）
        if equipment_type:
            self.logger.info(
                f"Phase 1 skipped: equipment_type provided by caller: {equipment_type}"
            )
            type_output = ExpertOutput(
                expert_type="EquipmentTypeExpert",
                success=True,
                data={
                    "equipment_type": equipment_type,
                    "confidence": 1.0,
                    "evidence": "由调用者指定，跳过自动判别",
                },
            )
            confidence = 1.0
            self._content.send_progress_with_data(
                1, total=3, message=f"Equipment type provided: {equipment_type}",
                ui_event={
                    "event_type": "type_detected",
                    "equipment_type": equipment_type,
                    "confidence": confidence,
                },
            )
        else:
            self._content.send_progress_with_data(0.5, total=3, message="Detecting equipment type")
            type_output = self._detect_equipment_type(str(image), context, loaded_image)
            equipment_type = type_output.data.get("equipment_type", "unknown")
            confidence = type_output.data.get("confidence", 0.0)
            self._content.send_progress_with_data(
                1, total=3, message=f"Equipment type detected: {equipment_type}",
                ui_event={
                    "event_type": "type_detected",
                    "equipment_type": equipment_type,
                    "confidence": confidence,
                },
            )

        if self._cancel_event and self._cancel_event.is_set():
            raise CancelledByClientError("客户端取消（设备类型判别后）")

        # Phase 2: 装配信息提取（按类型路由）
        self._content.send_progress_with_data(1.5, total=3, message="Extracting assembly data")
        assembly_output = self._extract_assembly(
            str(image),
            {**context, "equipment_type": type_output.data["equipment_type"]},
            loaded_image,
        )
        self._content.send_progress_with_data(
            2, total=3, message="Assembly data extracted",
            ui_event={
                "event_type": "assembly_extracted",
                "success": assembly_output.success,
            },
        )

        if self._cancel_event and self._cancel_event.is_set():
            raise CancelledByClientError("客户端取消（装配信息提取后）")

        result = self._build_result(
            image_path=str(image),
            equipment_id=equipment_id,
            type_output=type_output,
            assembly_output=assembly_output,
        )

        self._content.send_progress_with_data(3, total=3, message="Equipment assembly extraction completed")
        self.logger.info("=" * 80)
        self.logger.info(f"Workflow {self.workflow_name} completed")
        self.logger.info("=" * 80)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_equipment_type(
        self, image_path: str, context: dict[str, Any], loaded_image=None
    ) -> ExpertOutput:
        self.logger.info("Phase 1: detecting equipment type")
        try:
            output = self.type_expert.analyze(
                image_path, context=context, loaded_image=loaded_image,
                cancel_event=self._cancel_event,
            )
        except PFDAnalysisError:
            raise
        except Exception as e:
            raise PFDAnalysisError(
                f"Workflow {self.workflow_name} failed at type detection phase: {e}"
            ) from e

        if not output.success:
            raise PFDAnalysisError(f"EquipmentTypeExpert failed: {output.errors}")

        equipment_type = output.data.get("equipment_type", "unknown")
        confidence = output.data.get("confidence", 0.0)
        self.logger.info(
            f"Phase 1 complete: equipment_type={equipment_type} confidence={confidence}"
        )
        return output

    def _extract_assembly(
        self, image_path: str, context: dict[str, Any], loaded_image=None
    ) -> ExpertOutput:
        equipment_type = context.get("equipment_type", "unknown")
        expert = self._select_assembly_expert(equipment_type)
        expert_context = self._build_expert_context(context, equipment_type)
        self.logger.info(
            f"Phase 2: extracting assembly data (equipment_type={equipment_type}, expert={expert.expert_type})"
        )
        try:
            output = expert.analyze(
                image_path, context=expert_context, loaded_image=loaded_image,
                cancel_event=self._cancel_event,
            )
        except PFDAnalysisError:
            raise
        except Exception as e:
            raise PFDAnalysisError(
                f"Workflow {self.workflow_name} failed at assembly extraction phase: {e}"
            ) from e

        if not output.success:
            raise PFDAnalysisError(f"{expert.__class__.__name__} failed: {output.errors}")

        self.logger.info("Phase 2 complete: assembly data extracted")
        return output

    def _select_assembly_expert(self, equipment_type: str):
        """根据设备类型选择装配提取专家。"""
        if equipment_type == "reactor":
            return self.reactor_assembly_expert
        # column_tray / column_packed / unknown → ColumnAssemblyExpert
        # ColumnAssemblyExpert._build_prompt 会根据 column_type 选择提示词
        return self.column_assembly_expert

    @staticmethod
    def _build_expert_context(
        context: dict[str, Any], equipment_type: str
    ) -> dict[str, Any]:
        """根据设备类型为对应专家构建上下文。

        - column_tray/column_packed/unknown → ColumnAssemblyExpert：
            注入 column_type（tray/packed）和 column_id
        - reactor → ReactorAssemblyExpert：
            注入 reactor_id
        """
        equipment_id = context.get("equipment_id", "") or context.get("source_image_id", "")
        if equipment_type == "reactor":
            return {
                **context,
                "reactor_id": equipment_id,
                "source_image_id": equipment_id,
            }
        # column 系列
        column_type = ""
        if equipment_type == "column_tray":
            column_type = "tray"
        elif equipment_type == "column_packed":
            column_type = "packed"
        return {
            **context,
            "column_type": column_type,
            "column_id": equipment_id,
            "source_image_id": equipment_id,
        }

    def _build_result(
        self,
        image_path: str,
        equipment_id: str,
        type_output: ExpertOutput,
        assembly_output: ExpertOutput,
    ) -> dict[str, Any]:
        type_data = type_output.data or {}
        assembly_data = assembly_output.data or {}

        warnings: list[str] = []
        warnings.extend(type_output.warnings or [])
        warnings.extend(type_data.get("warnings", []))
        warnings.extend(assembly_output.warnings or [])
        warnings.extend(assembly_data.get("warnings", []))

        equipment_type = type_data.get("equipment_type", "unknown")

        # 根据 equipment_type 选择装配结果字段
        if equipment_type == "reactor":
            assembly_result = {"reactor_design": assembly_data.get("reactor_design", {})}
        else:
            assembly_result = {"distillation_column": assembly_data.get("distillation_column", {})}

        if equipment_type == "unknown":
            warnings.append(
                "equipment type unknown, assembly extracted with default column expert"
            )

        return {
            "status": "success" if not warnings else "partial",
            "workflow": self.workflow_name,
            "equipment_id": equipment_id,
            "equipment_type": equipment_type,
            "type_detection": {
                "equipment_type": equipment_type,
                "evidence": type_data.get("evidence", ""),
                "confidence": type_data.get("confidence", 0.0),
            },
            "assembly": assembly_result,
            "warnings": self._dedupe_warnings(warnings),
        }

    @staticmethod
    def _dedupe_warnings(items: list[Any]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result
