from typing import Any

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt


@register_prompt("table", "v1")
class TablePromptBuilderV1(PromptBuilder):
    expert_type = "table"
    version = "v1"
    description = "V1 表格提取版：输出Markdown格式表格，支持多行表头保留，空单元格用[空]标记，支持设备表/物料表/工艺条件表类型提示，含列数一致性检查清单"

    _ROLE = """
        你是一个专业的化工工程图纸表格提取专家。你的任务是从图片中准确识别并提取表格内容。
        """

    _RULES = """
        【核心要求 - 必须严格遵守】

        1. 输出格式：
           - 直接输出Markdown表格，不要输出任何分析、思考或说明文字
           - 格式：| 列1 | 列2 | 列3 | ... |
           - 每行必须有相同数量的列，用 | 分隔

        2. 表头处理（完全保持原始格式，非常重要）：
           - 如果原表有多行表头，必须完整保留多行表头结构
           - 绝对不要合并或简化多行表头
           - 表头的每一行都要单独输出，列数必须与数据行完全一致
           - 关键：先数清楚数据行有多少列，然后确保表头的每一行都有相同的列数
           - 如果表头跨越多行，每一行都必须有相同的列数（用[空]填充空白位置）

        3. 空单元格处理（非常重要，必须严格遵守）：
           - 空单元格必须用特殊标记 "[空]" 表示
           - 不要用空白、空格或其他符号
           - 绝对不能省略或压缩连续的空单元格
           - 每一列都必须有对应的值，即使是连续多个空单元格也要逐个输出
           - 在输出每一行之前，先数清楚这一行应该有多少列，确保列数完全一致
           - 示例1：| 项目A | [空] | 数值1 | [空] |
           - 示例2（连续空单元格）：| 项目B | [空] | [空] | [空] | [空] | [空] | [空] | 数值2 |
           - 错误示例（❌不要这样）：| 项目B | [空] | 数值2 |  ← 这样会丢失列！

        4. 格式对齐要求：
           - 完全按照图片中表格的原始格式输出
           - 每一行必须与图片中的行一一对应
           - 每一列必须与图片中的列一一对应
           - 数清楚每一列，即使连续多个空单元格也要逐个标记
           - 确保每一行的列数完全相同（包括表头的每一行）
           - 建议：输出每一行时，在心里默数列数，确保列数一致

        5. 数据完整性：
           - 数字和文字要准确识别，严格保持原始格式
           - 合并单元格拆分为多个相同内容的单元格
           - 保持表格的原始结构，不要简化或合并

        6. 特殊表格类型处理：
           - 设备表：关注设备位号、名称、类型、数量等字段
           - 物料表：关注物料名称、组分、流量、温度、压力等字段
           - 工艺条件表：关注温度、压力、流量、相态等参数
           - 图例表：关注符号、说明、备注等字段

        7. 检查清单（输出前必须确认）：
           □ 每一行的列数完全相同（包括表头的每一行）
           □ 多行表头完整保留，且每行列数一致
           □ 连续的空单元格没有压缩
           □ 所有空单元格都用 [空] 标记
           □ 表格结构与原图完全一致
        """

    _OUTPUT_FORMAT = """
        【输出示例】
        | 序号 | 设备位号 | 设备名称 | 设备类型 | 数量 | 备注 |
        |------|----------|----------|----------|------|------|
        | 1 | P-101 | 进料泵 | 离心泵 | 2 | 一用一备 |
        | 2 | E-102 | 原料预热器 | 换热器 | 1 | [空] |
        | 3 | R-103 | 反应器 | 固定床 | 1 | [空] |
        """

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]

        if context.has_image_size:
            sections.append(self.build_image_size_section(context.image_size))

        if context.has_process_description:
            sections.append(self.build_process_description_section(context.process_description))

        table_type = context.extra.get("table_type", "general")
        type_hint = ""
        if table_type == "equipment":
            type_hint = "\n【表格类型提示】当前提取的是工艺设备表，请重点关注设备位号、名称、类型、数量等字段。\n"
        elif table_type == "material":
            type_hint = "\n【表格类型提示】当前提取的是物料表，请重点关注物料名称、组分、流量、温度、压力等字段。\n"

        if type_hint:
            sections.append(type_hint)

        sections.extend([self._RULES, self._OUTPUT_FORMAT])

        return "\n".join(s for s in sections if s)

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "table": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "header": {"type": "array", "items": {"type": "string"}},
                            "rows": {
                                "type": "array",
                                "items": {"type": "array", "items": {"type": "string"}},
                            },
                            "col_count": {"type": "integer"},
                            "row_count": {"type": "integer"},
                        },
                    },
                },
            },
        }
