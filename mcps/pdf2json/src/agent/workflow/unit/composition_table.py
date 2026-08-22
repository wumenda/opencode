"""CompositionTable Workflow -- 组分表信息提取工作流。

将 ``CompositionTableExpert`` 的单页提取与跨页聚合整合为一个独立工作流：

    image_path (单张图片，由调用端从 PDF 渲染)
      -> CompositionTableExpert.analyze() -> 单页 components / streams

多页场景由调用端逐页调用 ``analyze`` 后，再调用 ``aggregate`` 跨页聚合
（components 按名称去重 + streams 全部汇总）。

输入为单张图片路径（PDF -> 图片的渲染由调用端负责，见 AGENT.md 输入边界），
工作流不感知 PDF 与页码。
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from src.agent.experts.unit.composition_table import CompositionTableExpert
from src.agent.models import ExpertOutput
from src.agent.workflow.core import BaseWorkflow
from duck.content import Content
from duck.host_client import HostClient
from src.core import Settings, get_logger
from src.core.infra.exceptions import CancelledByClientError, PFDAnalysisError

logger = get_logger(__name__)


class CompositionTableWorkflow(BaseWorkflow):
    """组分表信息提取工作流。

    接收由调用端渲染好的单张图片，调用 :class:`CompositionTableExpert` 提取该页
    组分表。多页 PDF 场景由调用端逐页调用 ``analyze`` 后，调用 ``aggregate``
    跨页聚合为统一的 components + streams 输出。

    本工作流不感知 PDF 与页码，PDF -> 图片的渲染由调用端（entry / mcp_server）负责。
    """

    workflow_name = "composition_table"

    def __init__(
        self,
        settings: Settings,
        prompt_version: Optional[str] = None,
        content: Optional[Content] = None,
        host_client: Optional[HostClient] = None,
    ) -> None:
        self._prompt_version = prompt_version
        super().__init__(
            settings=settings,
            content=content,
            host_client=host_client,
        )

    def _init_experts(self) -> None:
        self.expert = CompositionTableExpert(
            settings=self.settings,
            prompt_version=self._prompt_version,
        )

    def _log_workflow_info(self) -> None:
        logger.info("=" * 60)
        logger.info(f"Workflow: {self.workflow_name}")
        logger.info(
            f"  CompositionTable Expert prompt version: "
            f"{self.expert._prompt_builder.version}"
        )
        logger.info("-" * 60)
        logger.info("analyze: CompositionTableExpert - 单页组分表提取")
        logger.info("aggregate: 跨页聚合 components + streams")
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        image_path: str,
        *,
        page_index: int = 0,
        cancel_event: Optional[threading.Event] = None,
    ) -> dict[str, Any]:
        """从单张图片提取组分表信息。

        Args:
            image_path: 由调用端从 PDF 渲染好的单张图片路径。
            page_index: 页码（0-based），仅用于结果标注，默认 0。

        Returns:
            单页结果 dict，包含：
                - page_index / image_path / has_composition_table
                - extracted: 该页 components / streams
                - warnings: 本页告警列表

        多页场景：调用端逐页调用本方法收集结果后，再调用 :meth:`aggregate` 聚合。
        """
        self._cancel_event = cancel_event
        # 通过 HostClient 加载图片为内存 Image（不触碰本地文件 API）
        loaded_image = self._load_image(image_path) if self._host_client else None

        self._content.send_progress_with_data(
            0, total=2, message="Starting composition table extraction"
        )

        self.logger.info(f"--- Page {page_index}: {image_path} ---")
        try:
            expert_output: ExpertOutput = self.expert.analyze(
                image_path, loaded_image=loaded_image, cancel_event=self._cancel_event
            )
        except PFDAnalysisError:
            raise
        except Exception as e:
            raise PFDAnalysisError(
                f"Workflow {self.workflow_name} failed at page {page_index}: {e}"
            ) from e

        extracted = expert_output.data or {}
        warnings = list(expert_output.warnings or [])
        warnings.extend(extracted.get("warnings", []))

        has_table = bool(extracted.get("components")) or bool(extracted.get("streams"))
        page_result: dict[str, Any] = {
            "page_index": page_index,
            "has_composition_table": has_table,
            "extracted": extracted,
            "warnings": warnings,
        }

        self._content.send_progress_with_data(
            1,
            total=2,
            message=f"第 {page_index + 1} 页提取完成",
            ui_event={
                "event_type": "composition_page_extracted",
                "page_index": page_index,
                "has_table": has_table,
                "partial_extracted": {
                    "components": extracted.get("components", []),
                    "streams": extracted.get("streams", []),
                },
            },
        )

        return page_result

    @staticmethod
    def aggregate(page_results: list[dict[str, Any]]) -> dict[str, Any]:
        """跨页聚合各页结果：components 按名称去重，streams 全部汇总。

        Args:
            page_results: 由 :meth:`analyze` 逐页返回的结果列表。

        Returns:
            ``{"components": [...], "streams": [...]}``
        """
        components: list[dict[str, Any]] = []
        seen_components: set[str] = set()
        streams: list[dict[str, Any]] = []

        for page in page_results:
            extracted = page.get("extracted", {}) or {}

            for comp in extracted.get("components", []) or []:
                if not isinstance(comp, dict):
                    continue
                name = str(comp.get("name", "")).strip()
                if not name or name in seen_components:
                    continue
                seen_components.add(name)
                components.append(
                    {
                        "name": name,
                        "molecular_weight": comp.get("molecular_weight"),
                    }
                )

            for stream in extracted.get("streams", []) or []:
                if isinstance(stream, dict):
                    streams.append(stream)

        return {"components": components, "streams": streams}
