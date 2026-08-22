"""ProcessPackage Workflow — 工艺包章节信息提取工作流。

将 ``ProcessPackageExpert`` 与 PDF 章节抽取整合为一个独立工作流：

    PDF (多页)
      → PdfSectionExtractor (书签优先+正则回退) → 章节文本
      → ProcessPackageExpert.analyze() → 工序说明 / 反应方程式

与基于图像的拓扑工作流不同，本工作流的输入是 PDF 路径（纯文本通道），
因此不继承自 :class:`BaseWorkflow`，只复用其轻量结构与产物保存约定。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional

from src._internal import PdfSectionExtractor, PdfSectionResult
from src.agent.experts.unit.process_package import ProcessPackageExpert
from src.agent.models import ExpertOutput
from src.agent.workflow.core import BaseWorkflow
from duck.content import Content
from duck.host_client import HostClient
from src.core import Settings, get_logger
from src.core.infra.exceptions import CancelledByClientError, PFDAnalysisError

logger = get_logger(__name__)


class ProcessPackageWorkflow(BaseWorkflow):
    """工艺包章节信息提取工作流。

    通过章节序号或标题关键词定位 PDF 章节，抽取整段文本后调用
    :class:`ProcessPackageExpert` 输出结构化的工序说明与反应方程式。
    """

    workflow_name = "process_package"

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
        self.expert = ProcessPackageExpert(
            settings=self.settings,
            prompt_version=self._prompt_version,
        )

    def _log_workflow_info(self) -> None:
        logger.info("=" * 60)
        logger.info(f"Workflow: {self.workflow_name}")
        logger.info(
            f"  ProcessPackage Expert prompt version: "
            f"{self.expert._prompt_builder.version}"
        )
        logger.info("-" * 60)
        logger.info("Phase 1: PdfSectionExtractor — 章节抽取（书签优先+正则回退）")
        logger.info("Phase 2: ProcessPackageExpert — 工序说明 / 反应方程式提取")
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        pdf_path: str,
        *,
        chapter_index: Optional[int] = None,
        chapter_title: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> dict[str, Any]:
        """从工艺包 PDF 提取结构化的工序说明与反应方程式。

        Args:
            pdf_path: 工艺包 PDF 文件路径。
            chapter_index: 顶层章节序号（1-based），与 chapter_title 二选一。
            chapter_title: 章节标题关键词（子串匹配，大小写不敏感）。

        Returns:
            dict 包含：
                - status: ``"success"`` / ``"partial"``
                - workflow / pdf_path / locator / total_pages
                - matched_sections / all_matched_page_numbers
                - filtered_text_length
                - expert_outputs.process_package: 提取的结构化数据
                - warnings: 合并的告警列表
        """
        self._cancel_event = cancel_event
        pdf = Path(pdf_path)
        if chapter_index is None and not chapter_title:
            raise PFDAnalysisError("必须指定 chapter_index 或 chapter_title 之一")

        self.logger.info("=" * 80)
        self.logger.info(f"Workflow: {self.workflow_name} started")
        self.logger.info(f"Input PDF: {pdf}")
        if chapter_index is not None:
            locator = f"chapter_index={chapter_index}"
        else:
            locator = f"chapter_title={chapter_title}"
        self.logger.info(f"Locator: {locator}")
        self.logger.info("=" * 80)

        # 收到 PDF 即推送 解析PDF 阶段：携带 pdf_path，前端据此发起 read_image 渲染 PDF 内容
        self._content.send_progress_with_data(
            0, total=3, message="PDF 已接收，解析 PDF 中…",
            ui_event={
                "event_type": "pdf_received",
                "partial_pdf_path": str(pdf),
            },
        )

        # 通过 host_client.get_file 读取输入 PDF 为 bytes（不触碰本地文件 API）
        pdf_bytes = self._load_pdf_bytes(str(pdf))

        # Phase 1: 章节抽取
        section_result = self._extract_chapter(
            pdf_bytes,
            chapter_index=chapter_index,
            chapter_title=chapter_title,
        )
        combined_text = section_result.combined_text
        if not combined_text.strip():
            raise PFDAnalysisError(
                f"章节抽取后无文本内容，请检查 PDF 或定位条件: {locator}"
            )

        all_page_numbers: list[int] = sorted(
            {p.page_number for sec in section_result.matched_sections for p in sec.pages}
        )
        self.logger.info(
            f"章节抽取完成：匹配章节 {len(section_result.matched_sections)} 个，"
            f"覆盖 {len(all_page_numbers)} 页，文本 {len(combined_text)} 字符"
        )
        self._content.send_progress_with_data(
            1, total=3, message="Chapter extraction completed",
            ui_event={
                "event_type": "chapter_extracted",
                "matched_section_count": len(section_result.matched_sections),
                "total_pages": section_result.total_pages,
                "text_length": len(combined_text),
                "partial_matched_sections": [
                    {
                        "title": sec.title,
                        "level": sec.level,
                        "start_page": sec.start_page,
                        "end_page": sec.end_page,
                        "page_count": len(sec.pages),
                        "page_numbers": [p.page_number for p in sec.pages],
                    }
                    for sec in section_result.matched_sections
                ],
                "partial_pdf_path": str(pdf),
                "partial_total_pages": section_result.total_pages,
            },
        )

        if self._cancel_event and self._cancel_event.is_set():
            raise CancelledByClientError("客户端取消（章节抽取后）")

        # Phase 2: ProcessPackageExpert 提取
        self._content.send_progress_with_data(1.5, total=3, message="Running ProcessPackageExpert")
        try:
            expert_output: ExpertOutput = self.expert.analyze(paragraph=combined_text, cancel_event=self._cancel_event)
        except PFDAnalysisError:
            raise
        except Exception as e:
            raise PFDAnalysisError(
                f"Workflow {self.workflow_name} failed at expert phase: {e}"
            ) from e

        extracted = expert_output.data or {}
        warnings = list(section_result.warnings)
        warnings.extend(expert_output.warnings or [])
        warnings.extend(extracted.get("warnings", []))

        if not expert_output.success:
            raise PFDAnalysisError(
                f"ProcessPackageExpert failed: {expert_output.errors}"
            )

        self._content.send_progress_with_data(
            2, total=3, message="Process package expert completed",
            ui_event={
                "event_type": "expert_complete",
                "success": expert_output.success,
                "has_data": bool(extracted),
            },
        )

        result: dict[str, Any] = {
            "status": "success" if not warnings else "partial",
            "workflow": self.workflow_name,
            "pdf_path": str(pdf),
            "locator": locator,
            "total_pages": section_result.total_pages,
            "matched_section_count": len(section_result.matched_sections),
            "matched_sections": [
                {
                    "title": sec.title,
                    "level": sec.level,
                    "start_page": sec.start_page,
                    "end_page": sec.end_page,
                    "page_count": len(sec.pages),
                    "page_numbers": [p.page_number for p in sec.pages],
                }
                for sec in section_result.matched_sections
            ],
            "all_matched_page_numbers": all_page_numbers,
            "filtered_text_length": len(combined_text),
            "filtered_text": combined_text,
            "expert_outputs": {"process_package": extracted},
            "warnings": warnings,
        }

        self._content.send_progress_with_data(3, total=3, message="Process package extraction completed")
        self.logger.info("=" * 80)
        self.logger.info(f"Workflow {self.workflow_name} completed successfully")
        self.logger.info("=" * 80)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_chapter(
        self,
        pdf_source: "str | bytes",
        *,
        chapter_index: Optional[int],
        chapter_title: Optional[str],
    ) -> PdfSectionResult:
        extractor = PdfSectionExtractor()
        section_result = extractor.extract_chapter(
            pdf_source,
            chapter_index=chapter_index,
            chapter_title=chapter_title,
        )
        if not section_result.matched_sections:
            raise PFDAnalysisError(
                "未匹配到任何章节，请确认 chapter_index/chapter_title 与 PDF 内容是否一致。"
                f" warnings={section_result.warnings}"
            )
        return section_result
