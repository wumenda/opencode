"""工艺包段落信息提取专家。

从工艺包文档段落中提取工序说明、反应方程式等结构化信息。
与图像专家不同，本专家输入为纯文本，调用 text-only API。
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from src.agent.experts.core.base import BaseExpert
from src.agent.models import ExpertOutput
from src.agent.prompts import PromptContext, get_prompt_builder
from src.core import Settings, VisionAPIClient
from src.core.infra.exceptions import APIError, CancelledByClientError, PFDAnalysisError
from src.core.io.json_utils import parse_json_with_recovery
from src.core.models.unit.process_package import ProcessPackageInfo


class ProcessPackageExpert(BaseExpert):
    """从工艺包段落中提取工序说明和反应方程式。

    输入为工艺包文档的文本段落（由 PDF 段落提取工具筛选后提供），
    输出为 :class:`ProcessPackageInfo` 结构化数据。
    """

    expert_type = "process_package"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        enable_preprocessing: bool = False,
        prompt_version: Optional[str] = None,
        client: Optional[VisionAPIClient] = None,
    ) -> None:
        super().__init__(
            settings=settings,
            enable_preprocessing=enable_preprocessing,
            prompt_version=prompt_version,
            client=client,
        )
        self._prompt_builder = get_prompt_builder(
            "process_package", self._prompt_version
        )

    def _extract(self, image_path: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """图像模式提取 — 本专家为纯文本输入，该方法不会被调用。"""
        raise NotImplementedError(
            "ProcessPackageExpert is a text-only expert; "
            "use analyze(paragraph=...) instead."
        )

    def _build_prompt(self, context: Optional[dict[str, Any]] = None) -> str:
        context = context if isinstance(context, dict) else {}
        paragraph = context.get("paragraph", "")
        prompt_context = PromptContext(
            process_description=paragraph,
        )
        return self._prompt_builder.build(prompt_context)

    def _parse(self, raw_response: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info("Parsing process package extraction response")
        parse_result = parse_json_with_recovery(raw_response, expert_type=self.expert_type)
        if not parse_result.success or parse_result.data is None:
            return {
                "operation_description": "",
                "reaction_equation": "",
                "warnings": parse_result.warnings,
            }

        data = parse_result.data
        warnings = parse_result.warnings.copy()
        if parse_result.recovery_level > 0:
            warnings.append(f"JSON recovery level: {parse_result.recovery_level}")

        try:
            info = ProcessPackageInfo(
                operation_description=data.get("operation_description", ""),
                reaction_equation=data.get("reaction_equation", ""),
                warnings=warnings + data.get("warnings", []),
            )
            return info.model_dump()
        except Exception as e:
            self.logger.warning(f"Failed to validate ProcessPackageInfo: {e}")
            return {
                "operation_description": data.get("operation_description", ""),
                "reaction_equation": data.get("reaction_equation", ""),
                "warnings": warnings + [f"Model validation failed: {e}"],
            }

    def analyze(
        self,
        paragraph: str,
        context: Optional[dict[str, Any]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> ExpertOutput:
        """从工艺包段落中提取工序说明和反应方程式。

        Args:
            paragraph: 工艺包文档段落文本（通常由 PDF 段落提取工具筛选后提供）。
            context: 额外上下文（可选）。
            cancel_event: 客户端取消信号（可选），在 LLM 调用前后检查。

        Returns:
            ExpertOutput，data 中包含 operation_description / reaction_equation / warnings。
        """
        if not paragraph or not paragraph.strip():
            raise PFDAnalysisError("paragraph is empty")

        self.logger.info(
            f"Starting process package extraction ({len(paragraph)} characters)"
        )

        ctx = dict(context) if isinstance(context, dict) else {}
        ctx["paragraph"] = paragraph

        try:
            prompt = self._build_prompt(ctx)

            # 取消检查点：LLM 调用前
            if cancel_event and cancel_event.is_set():
                raise CancelledByClientError(
                    "客户端取消（process_package VLM 调用前）"
                )

            raw_response, reasoning_content = self.client.call_api_text_only(
                prompt=prompt,
                provider_config=self.provider_config,
                expert_config=self.expert_config,
            )

            # 取消检查点：LLM 调用后
            if cancel_event and cancel_event.is_set():
                raise CancelledByClientError(
                    "客户端取消（process_package VLM 调用后）"
                )

            if reasoning_content and self.settings.save_thinking:
                self._save_thinking_content(reasoning_content, "process_package")

            parsed = self._parse(raw_response, ctx)

            return ExpertOutput(
                expert_type=self.expert_type,
                success=True,
                data=parsed,
                reasoning_content=reasoning_content,
                warnings=parsed.get("warnings", []),
            )

        except APIError as e:
            self.logger.error(f"API call failed for {self.expert_type}: {e}")
            raise
        except PFDAnalysisError as e:
            self.logger.error(f"Analysis error in {self.expert_type}: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in {self.expert_type}: {e}")
            raise PFDAnalysisError(f"Unexpected error in {self.expert_type}: {e}") from e
