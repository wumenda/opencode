"""Prompt builder for composition table (组分表) extraction from images."""

from __future__ import annotations

from typing import Any

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt


@register_prompt("composition_table", "v1")
class CompositionTablePromptBuilderV1(PromptBuilder):
    """从图片中识别并提取组分表（components + streams）信息。

    输出严格 JSON，结构对应 :class:`~src.core.models.unit.composition_table.CompositionTable`：
        - components: 组分定义列表（name + molecular_weight）
        - streams: 流股列表（stream_id / flow_rate / composition /
          temperature / pressure / phase）
    """

    expert_type = "composition_table"
    version = "v1"
    description = "组分表信息提取（图像输入，输出 components + streams 结构化 JSON）"

    _ROLE = """\
        【角色】
        你是化工工艺图纸组分表识别专家。你的任务是：仔细观察输入图片，
        从中识别"组分表 / 物料平衡表 / 流股组成表"，并提取其中的组分信息与各流股的组成数据。
        """

    _TASK_SCOPE = """\
        【任务范围】
        1. 组分表通常以表格形式出现，可能标题为"组分表"、"物料平衡表"、"流股组成表"、
           "Stream Composition"、"Material Balance"等。
        2. 需要提取两类信息：
           (a) components —— 组分定义列表：每个组分包含名称(name)和分子量(molecular_weight)。
               分子量可能单独列出，也可能需要从表头/注释中识别；无法识别时填 null。
           (b) streams —— 流股列表：每个流股包含编号(stream_id)、流量(flow_rate)、
               组成(composition)、温度(temperature)、压力(pressure)、相态(phase)。
        3. 若图片中不存在组分表，返回空列表：{"components": [], "streams": []}。
        """

    _FIELD_RULES = """\
        【字段说明与提取规则】

        1. components[]（组分定义）：
           - name: 组分名称，严格按原图文字填写（如 "水"、"甲醇"、"TAME"、"N-P"）。
           - molecular_weight: 分子量数值（g/mol）。原图未给出则填 null。

        2. streams[]（流股）：
           - stream_id: 流股编号（如 "1"、"2"）。原图无编号时填空字符串 ""。
           - flow_rate: {"value": 数值, "unit": 单位字符串}
               单位如 "kg/h"、"kmol/h"、"t/h"。无法识别时 value 填 null、unit 填 ""。
           - composition[]: 该流股中每个组分的组成
               {"component": 组分名称, "mole_fraction": 摩尔分数, "mass_fraction": 质量分数}
               · mole_fraction / mass_fraction 取值 0~1；原图用百分比时需除以 100。
               · 表中未列出某组分，则该组分不必出现在该流股的 composition 中。
               · 若原图仅给出一类分数（只有摩尔或只有质量），另一类填 null。
               · 若 composition 列全部为 0 或未给出，仍按组分逐条输出，分数填 0 或 null。
           - temperature: {"value": 数值, "unit": 单位}，单位如 "℃"、"K"。
           - pressure: {"value": 数值, "unit": 单位}，单位如 "MPa"、"kPa"、"bar"。
           - phase: 相态字符串，如 "Liq"、"Vap"、"Li/Va"；无则填 ""。

        3. 多个流股的 composition 应共享同一套组分（与 components 列表对应）。
        4. 跨页连续的组分表：只提取当前图片可见部分，不要补全未出现的行。
        """

    _RULES = """\
        【核心要求 — 必须严格遵守】
        1. 只输出纯 JSON，不要输出 markdown 代码块、不要输出解释或思考文字。
        2. 所有数值严格按原图填写，不要编造、不要做单位换算（百分比→小数除外）。
        3. 数字识别要精确，保留原图有效数字位数；科学计数法按原样输出（如 6.29e3）。
        4. 若表格分多列对应多个流股，需将每个流股单独拆分为 streams 数组的一个元素，
           其 composition 对应该流股所在列的各组分分数。
        5. 无法识别或缺失的字段：数值填 null，字符串填 ""，不要省略字段。
        注意：一般来说，组分表是一个表格，按照表格的对应规则去提取信息，一般是一列是一条流股的信息。
        """

    _OUTPUT_FORMAT = """\
        【输出 JSON 结构示例】
        {
          "components": [
            {"name": "水", "molecular_weight": 18.01528},
            {"name": "甲醇", "molecular_weight": 32.04216}
          ],
          "streams": [
            {
              "stream_id": "1",
              "flow_rate": {"value": 6294.7232785603, "unit": "kg/h"},
              "composition": [
                {"component": "水", "mole_fraction": 0.001166, "mass_fraction": 0.000297},
                {"component": "甲醇", "mole_fraction": 0.0, "mass_fraction": 0.0}
              ],
              "temperature": {"value": 50.11, "unit": "℃"},
              "pressure": {"value": 1.1, "unit": "MPa"},
              "phase": "Liq"
            }
          ],
          "warnings": []
        }
        """

    _MANDATORY_CHECK = """\
        【强制自检 — 输出前逐项执行】
        □ 检查1: 输出是否为纯 JSON（无 markdown、无解释文字）？
        □ 检查2: components 与 streams.composition 的组分名称是否一致对应？
        □ 检查3: 百分比是否已换算为 0~1 的小数？
        □ 检查4: 缺失数值是否填 null、缺失字符串是否填 ""，而非省略字段？
        □ 检查5: 所有数据是否来自原图，未编造？
        □ 检查6: 图片中无组分表时，是否返回 {"components": [], "streams": []}？
        """

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE, self._TASK_SCOPE, self._FIELD_RULES]

        if context.has_image_size:
            sections.append(self.build_image_size_section(context.image_size))

        if context.has_process_description:
            sections.append(self.build_process_description_section(context.process_description))

        sections.extend([self._RULES, self._OUTPUT_FORMAT, self._MANDATORY_CHECK])

        return "\n".join(section for section in sections if section)

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "components": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "molecular_weight": {"type": ["number", "null"]},
                        },
                        "required": ["name"],
                    },
                },
                "streams": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "stream_id": {"type": "string"},
                            "flow_rate": {
                                "type": "object",
                                "properties": {
                                    "value": {"type": ["number", "null"]},
                                    "unit": {"type": "string"},
                                },
                            },
                            "composition": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "component": {"type": "string"},
                                        "mole_fraction": {"type": ["number", "null"]},
                                        "mass_fraction": {"type": ["number", "null"]},
                                    },
                                },
                            },
                            "temperature": {
                                "type": "object",
                                "properties": {
                                    "value": {"type": ["number", "null"]},
                                    "unit": {"type": "string"},
                                },
                            },
                            "pressure": {
                                "type": "object",
                                "properties": {
                                    "value": {"type": ["number", "null"]},
                                    "unit": {"type": "string"},
                                },
                            },
                            "phase": {"type": "string"},
                        },
                    },
                },
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["components", "streams"],
        }
