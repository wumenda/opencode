"""PFDRefluxWorkflow —— PFD 塔与反应器回流结构分析工作流。

将 ``PFDRefluxExpert`` 与单张 PFD 图片整合为一个独立工作流：

    PFD 图片（单张）
      → PFDRefluxExpert.analyze() → towers / reactors 结构化结果

输入为 PFD 图纸图片路径（单张，PDF 由调用端逐页渲染），输出为塔与反应器
回流结构分析 JSON。多页 PDF 由调用端逐页调用后聚合，工作流只处理单张图片。
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from src.agent.experts.unit.pfd_reflux import PFDRefluxExpert
from src.agent.models import ExpertOutput
from src.agent.workflow.core import BaseWorkflow
from duck.content import Content
from duck.host_client import HostClient
from src.core import Settings, get_logger
from src.core.infra.exceptions import CancelledByClientError, PFDAnalysisError

logger = get_logger(__name__)


class PFDRefluxWorkflow(BaseWorkflow):
    """PFD 塔与反应器回流结构分析工作流。

    对单张 PFD 图纸图片调用 :class:`PFDRefluxExpert`，提取所有塔与反应器，
    判断回流结构，并输出塔回流详情与设备操作条件。
    """

    workflow_name = "pfd_reflux"

    def __init__(
        self,
        settings: Settings,
        process_description: str = "",
        prompt_version: Optional[str] = None,
        content: Optional[Content] = None,
        host_client: Optional[HostClient] = None,
    ) -> None:
        self._process_description = process_description
        self._prompt_version = prompt_version
        super().__init__(
            settings=settings,
            content=content,
            host_client=host_client,
        )

    def _init_experts(self) -> None:
        self.expert = PFDRefluxExpert(
            settings=self.settings,
            process_description=self._process_description,
            prompt_version=self._prompt_version,
        )

    def _log_workflow_info(self) -> None:
        logger.info("=" * 60)
        logger.info(f"Workflow: {self.workflow_name}")
        logger.info(
            f"  PFDReflux Expert prompt version: "
            f"{self.expert._prompt_builder.version}"
        )
        logger.info(
            f"  Process description: {'loaded' if self._process_description else 'none'}"
        )
        logger.info("-" * 60)
        logger.info("Phase 1: PFDRefluxExpert — 塔与反应器回流结构提取")
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        image_path: str,
        cancel_event: Optional[threading.Event] = None,
    ) -> dict[str, Any]:
        """从 PFD 图片提取塔与反应器回流结构信息。

        Args:
            image_path: PFD 图纸图片路径（单张）。

        Returns:
            dict 包含：
                - status: ``"success"`` / ``"partial"``
                - workflow / image_path
                - expert_outputs.pfd_reflux: 专家输出
                - towers: 塔信息列表
                - reactors: 反应器信息列表
                - warnings: 合并的告警列表
        """
        self._cancel_event = cancel_event
        logger.info("=" * 80)
        logger.info(f"Workflow {self.workflow_name} started")
        logger.info(f"Input image: {image_path}")
        logger.info("=" * 80)

        self._content.send_progress_with_data(0, total=2, message="Starting PFD reflux analysis")

        # 通过 HostClient 加载图片为内存 Image（不触碰本地文件 API）
        loaded_image = self._load_image(image_path) if self._host_client else None

        try:
            expert_output: ExpertOutput = self.expert.analyze(
                image_path, loaded_image=loaded_image, cancel_event=self._cancel_event
            )
        except PFDAnalysisError:
            raise
        except Exception as e:
            raise PFDAnalysisError(
                f"Workflow {self.workflow_name} failed: {e}"
            ) from e

        extracted = expert_output.data or {}
        towers = extracted.get("towers", [])
        reactors = extracted.get("reactors", [])
        self._content.send_progress_with_data(
            1, total=2, message="Extraction completed",
            ui_event={
                "event_type": "extraction_complete",
                "success": expert_output.success,
                "towers": len(towers),
                "reactors": len(reactors),
            },
        )

        warnings: list[str] = list(expert_output.warnings or [])
        warnings.extend(extracted.get("warnings", []))

        result: dict[str, Any] = {
            "status": "success" if not warnings else "partial",
            "workflow": self.workflow_name,
            "expert_outputs": {
                "pfd_reflux": expert_output.model_dump(),
            },
            "towers": extracted.get("towers", []),
            "reactors": extracted.get("reactors", []),
            "warnings": warnings,
        }

        self._content.send_progress_with_data(2, total=2, message="PFD reflux analysis completed")
        logger.info("=" * 80)
        logger.info(f"Workflow {self.workflow_name} completed")
        logger.info("=" * 80)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

