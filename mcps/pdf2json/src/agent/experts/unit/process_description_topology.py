"""工艺说明文档拓扑提取专家。

从工艺流程说明文档（PDF 文本）中提取主工艺设备之间的连接关系。
与图像专家不同，本专家输入为纯文本，调用 text-only API。
"""

from __future__ import annotations

from typing import Any, Optional

from src.agent.experts.core.base import BaseExpert
from src.agent.models import ExpertOutput
from src.agent.prompts import PromptContext, get_prompt_builder
from src.core import Settings, VisionAPIClient
from src.core.infra.exceptions import APIError, PFDAnalysisError
from src.core.io.json_utils import parse_json_with_recovery


class ProcessDescriptionTopologyExpert(BaseExpert):
    """从工艺流程说明文本中提取主工艺设备间连接拓扑。

    输入为工艺流程说明文本（由入口脚本从 PDF 中提取），
    输出为设备节点列表和物料连接关系列表。
    """

    expert_type = "process_description_topology"

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
            "process_description_topology", self._prompt_version
        )

    def _extract(self, image_path: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """图像模式提取 — 本专家为纯文本输入，该方法不会被调用。"""
        raise NotImplementedError(
            "ProcessDescriptionTopologyExpert is a text-only expert; "
            "use analyze(process_description=...) instead."
        )

    def _build_prompt(self, context: Optional[dict[str, Any]] = None) -> str:
        context = context if isinstance(context, dict) else {}
        process_description = context.get("process_description", "")
        prompt_context = PromptContext(
            process_description=process_description,
        )
        return self._prompt_builder.build(prompt_context)

    def _parse(self, raw_response: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.logger.info("Parsing process description topology response")
        parse_result = parse_json_with_recovery(raw_response, expert_type=self.expert_type)
        if not parse_result.success or parse_result.data is None:
            return {"equipment": [], "connections": [], "warnings": parse_result.warnings}

        data = parse_result.data
        warnings = parse_result.warnings.copy()
        if parse_result.recovery_level > 0:
            warnings.append(f"JSON recovery level: {parse_result.recovery_level}")

        return {
            "document_name": data.get("document_name", ""),
            "equipment": data.get("equipment", []),
            "connections": data.get("connections", []),
            "warnings": warnings + data.get("warnings", []),
            "recovery_level": parse_result.recovery_level,
        }

    def analyze(
        self,
        process_description: str,
        context: Optional[dict[str, Any]] = None,
    ) -> ExpertOutput:
        """从工艺流程说明文本中提取装置拓扑。

        Args:
            process_description: 工艺流程说明文本（通常由 PDF 提取）。
            context: 额外上下文（可选）。

        Returns:
            ExpertOutput，data 中包含 equipment / connections / warnings。
        """
        if not process_description or not process_description.strip():
            raise PFDAnalysisError("process_description is empty")

        self.logger.info(
            f"Starting process description topology analysis "
            f"({len(process_description)} characters)"
        )

        ctx = dict(context) if isinstance(context, dict) else {}
        ctx["process_description"] = process_description

        try:
            prompt = self._build_prompt(ctx)

            raw_response, reasoning_content = self.client.call_api_text_only(
                prompt=prompt,
                provider_config=self.provider_config,
                expert_config=self.expert_config,
            )

            if reasoning_content and self.settings.save_thinking:
                self._save_thinking_content(reasoning_content, "process_description")

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
