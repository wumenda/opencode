"""Prompt builder for process package paragraph extraction."""

from __future__ import annotations

from typing import Any

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt


@register_prompt("process_package", "v1")
class ProcessPackagePromptBuilderV1(PromptBuilder):
    """从工艺包段落中提取工序说明和反应方程式。"""

    expert_type = "process_package"
    version = "v1"
    description = "工艺包段落信息提取（纯文本输入）"

    _ROLE = """\
        【角色】
        你是化工工艺包分析专家。你的任务是：阅读工艺包文档中的段落，从中提取工序说明和反应方程式信息。
        """

    _FIELD_RULES = """\
        【提取字段说明】
        1. operation_description（工序说明）：
           描述该工序/单元的操作过程、工艺原理、操作条件等说明性文字。
           - 提取该工序的完整操作说明，包括操作步骤、工艺条件（温度、压力、流量等）、操作原理
           - 保留原文中的关键技术参数和数据，不要省略具体数值
           - 如果原文分多个小节描述，合并为一段完整的说明

        2. reaction_equation（反应方程式）：
           该工序中涉及的化学反应方程式。
           - 如果有多个反应方程式（如主反应、副反应），用换行符分隔
           - 保留原文中的化学方程式格式，包括化学计量数、条件标注（如温度、催化剂）等
           - 如果原文中没有反应方程式（如该工序为物理分离过程），留空字符串 ""
        """

    _INPUT_SECTION = """\
        【输入文本】
        以下是工艺包文档中的段落内容，请仔细阅读并提取信息：

        {paragraph}
        """

    _OUTPUT_FORMAT = """\
        【输出要求】
        直接输出纯 JSON，不要输出 markdown，不要输出解释文字。

        {
          "operation_description": "工序说明内容...",
          "reaction_equation": "反应方程式...",
          "warnings": []
        }
        """

    _MANDATORY_CHECK = """\
        【强制自检 — 输出前逐项执行】
        □ 检查1: operation_description 是否完整包含了原文中关于工序操作的所有说明和关键参数？
        □ 检查2: reaction_equation 是否准确提取了所有反应方程式？如果没有则留空字符串。
        □ 检查3: 是否有编造原文中不存在的信息？所有内容必须来自原文。
        □ 检查4: 化学方程式是否完整保留了化学计量数和反应条件？
        """

    def build(self, context: PromptContext) -> str:
        paragraph = ""
        if context.has_process_description:
            paragraph = context.process_description
        elif "paragraph" in context.extra:
            paragraph = str(context.extra["paragraph"])

        sections = [self._ROLE, self._FIELD_RULES]

        if paragraph.strip():
            sections.append(self._INPUT_SECTION.format(paragraph=paragraph))

        sections.extend([self._OUTPUT_FORMAT, self._MANDATORY_CHECK])

        return "\n".join(section for section in sections if section)

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["operation_description", "reaction_equation"],
            "properties": {
                "operation_description": {"type": "string"},
                "reaction_equation": {"type": "string"},
                "warnings": {"type": "array"},
            },
        }
