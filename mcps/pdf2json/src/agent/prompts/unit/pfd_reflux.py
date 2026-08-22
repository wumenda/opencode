"""Prompt builder for PFD tower & reactor reflux structure analysis."""

from __future__ import annotations

from typing import Any

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt


@register_prompt("pfd_reflux", "v1")
class PFDRefluxPromptBuilderV1(PromptBuilder):
    """从 PFD 图纸图片中提取塔与反应器的回流结构信息。

    输出严格 JSON，结构对应 :class:`~src.core.models.unit.pfd_reflux.PFDRefluxAnalysis`：
        - towers: 塔信息列表（位号、回流结构判断、回流详情、塔操作条件）
        - reactors: 反应器信息列表（位号、回流/循环结构判断、反应器操作条件）
    """

    expert_type = "pfd_reflux"
    version = "v1"
    description = "PFD塔与反应器回流结构分析（图像输入，输出 towers + reactors 结构化 JSON）"

    _ROLE = """\
        【角色】
        你是化工 PFD（工艺流程图）回流结构分析专家。你的任务是：仔细观察输入的 PFD 图片，
        识别图中所有的塔（Tower/Column）和反应器（Reactor），并分析每个塔/反应器是否存在
        回流结构（即物料从该设备流出后又回到该设备自身的管线）。
        """

    _TASK_SCOPE = """\
        【任务范围】
        1. 识别图中所有的塔和反应器：
           - 塔：位号通常以 T、C 开头（如 T-101、C-201），图符为竖直长筒形设备。
           - 反应器：位号通常以 R 开头（如 R-101），图符为筒形/釜形设备。
        2. 对每个塔和反应器，判断是否存在回流结构：
           - 回流结构定义：物料从该设备某一端口流出，经过其他设备（如冷凝器、换热器）或不
             经过其他设备，最终又回到该设备自身的管线。
           - 塔顶回流：塔顶气相/液相物料流出后，经冷凝器等设备后又回到塔顶。
           - 塔釜回流：塔釜液相物料流出后，经再沸器等设备后又回到塔釜。
           - 反应器循环：反应器出口物料经分离/换热后又回到反应器入口（循环结构）。
        3. 对存在回流结构的塔，进一步判断：
           (a) 塔顶是否有冷凝器（冷凝器是一种换热器，用于冷凝塔顶气相物料）
           (b) 塔釜是否有再沸器（再沸器是一种换热器，用于加热塔釜液相物料产生气相回流）
           (c) 回流管线的回流量是多少
        4. 提取塔自身操作条件：塔顶温度、塔顶压力、塔釜温度、塔釜压力。
        5. 提取反应器自身操作条件：反应器温度、反应器压力。
        6. 若图片中不存在塔或反应器，返回空列表。
        """

    _FIELD_RULES = """\
        【字段说明与提取规则】

        1. towers[]（塔信息）：
           - tag: 塔的设备位号，严格按原图文字填写（如 "T-101"、"C-201"）。
           - name: 塔的名称（如 "脱甲烷塔"、"精馏塔"）。原图无名称时填 ""。
           - reflux_structure: 回流结构判断结果
               · has_reflux: 是否存在回流结构（true/false）
               · reflux_type: 回流类型，仅限以下值：
                 "top"（仅塔顶回流）、"bottom"（仅塔釜回流）、
                 "top_and_bottom"（塔顶与塔釜均有回流）、"none"（无回流）
               · description: 回流结构文字描述，说明回流管线的走向与经过的设备
                 （如"塔顶物料经E-101冷凝后部分回流至塔顶"）。无回流时填 ""。
           - reflux_detail: 回流详情（仅当 has_reflux=true 时填写，否则填 null）
               · has_top_condenser: 塔顶是否有冷凝器（true/false）；无法判断时填 null
               · has_bottom_reboiler: 塔釜是否有再沸器（true/false）；无法判断时填 null
               · top_condenser_tag: 塔顶冷凝器的设备位号（如 "E-101"）；无则填 ""
               · bottom_reboiler_tag: 塔釜再沸器的设备位号（如 "E-102"）；无则填 ""
               · reflux_flow_rate: {"value": 回流量数值, "unit": 单位}
                 单位如 "kg/h"、"t/h"、"m³/h"。无法识别时 value 填 null、unit 填 ""。
           - operating_conditions: 塔自身操作条件
               · top_temperature: {"value": 塔顶温度数值, "unit": 单位}，单位如 "℃"、"K"
               · top_pressure: {"value": 塔顶压力数值, "unit": 单位}，单位如 "MPa"、"kPa"
               · bottom_temperature: {"value": 塔釜温度数值, "unit": 单位}
               · bottom_pressure: {"value": 塔釜压力数值, "unit": 单位}

        2. reactors[]（反应器信息）：
           - tag: 反应器的设备位号，严格按原图文字填写（如 "R-101"）。
           - name: 反应器的名称（如 "加氢反应器"）。原图无名称时填 ""。
           - reflux_structure: 回流/循环结构判断结果（字段同 towers.reflux_structure）
               · 反应器可能存在循环结构（出口物料经分离后又回到入口），同样需判断。
           - operating_conditions: 反应器自身操作条件
               · temperature: {"value": 反应器温度数值, "unit": 单位}
               · pressure: {"value": 反应器压力数值, "unit": 单位}

        3. 回流结构判断要点：
           - 必须追踪管线的实际走向，确认物料"流出后又回到同一设备"，才算回流。
           - 塔顶物料流出后去往其他设备（如另一塔、储罐）不算回流。
           - 经过冷凝器/再沸器后再回到塔自身，算回流（这是最常见的塔回流形式）。
           - 仅凭设备图符无法判断回流，必须看管线连接与箭头方向。
        """

    _RULES = """\
        【核心要求 — 必须严格遵守】
        1. 只输出纯 JSON，不要输出 markdown 代码块、不要输出解释或思考文字。
        2. 所有数值严格按原图填写，不要编造、不要做单位换算。
        3. 数字识别要精确，保留原图有效数字位数。
        4. 设备位号严格按原图文字填写，保持格式一致（如 "T-101" 不可写为 "T101"）。
        5. 无法识别或缺失的字段：数值填 null，字符串填 ""，布尔值填 null，不要省略字段。
        6. reflux_detail 仅在 reflux_structure.has_reflux=true 时填写，否则必须为 null。
        7. 回流结构判断必须基于管线的实际连接关系，不可凭设备类型臆测。
        8. 不要遗漏图中任何塔或反应器；每个塔/反应器都要独立判断回流结构。
        """

    _OUTPUT_FORMAT = """\
        【输出 JSON 结构示例】
        {
          "towers": [
            {
              "tag": "T-101",
              "name": "脱甲烷塔",
              "reflux_structure": {
                "has_reflux": true,
                "reflux_type": "top_and_bottom",
                "description": "塔顶物料经E-101冷凝器冷凝后部分回流至塔顶；塔釜物料经E-102再沸器加热后回流至塔釜"
              },
              "reflux_detail": {
                "has_top_condenser": true,
                "has_bottom_reboiler": true,
                "top_condenser_tag": "E-101",
                "bottom_reboiler_tag": "E-102",
                "reflux_flow_rate": {"value": 12500.0, "unit": "kg/h"}
              },
              "operating_conditions": {
                "top_temperature": {"value": -96.0, "unit": "℃"},
                "top_pressure": {"value": 3.5, "unit": "MPa"},
                "bottom_temperature": {"value": 8.0, "unit": "℃"},
                "bottom_pressure": {"value": 3.6, "unit": "MPa"}
              }
            },
            {
              "tag": "T-102",
              "name": "",
              "reflux_structure": {
                "has_reflux": false,
                "reflux_type": "none",
                "description": ""
              },
              "reflux_detail": null,
              "operating_conditions": {
                "top_temperature": {"value": null, "unit": ""},
                "top_pressure": {"value": null, "unit": ""},
                "bottom_temperature": {"value": null, "unit": ""},
                "bottom_pressure": {"value": null, "unit": ""}
              }
            }
          ],
          "reactors": [
            {
              "tag": "R-101",
              "name": "加氢反应器",
              "reflux_structure": {
                "has_reflux": false,
                "reflux_type": "none",
                "description": ""
              },
              "operating_conditions": {
                "temperature": {"value": 350.0, "unit": "℃"},
                "pressure": {"value": 8.0, "unit": "MPa"}
              }
            }
          ],
          "warnings": []
        }
        """

    _MANDATORY_CHECK = """\
        【强制自检 — 输出前逐项执行】
        □ 检查1: 输出是否为纯 JSON（无 markdown、无解释文字）？
        □ 检查2: 图中所有塔和反应器是否都已识别（无遗漏）？
        □ 检查3: 每个塔/反应器的回流结构是否基于管线连接关系判断（而非臆测）？
        □ 检查4: reflux_detail 是否仅在 has_reflux=true 时填写（否则为 null）？
        □ 检查5: 回流类型 reflux_type 是否使用了规定枚举值（top/bottom/top_and_bottom/none）？
        □ 检查6: 缺失数值是否填 null、缺失字符串是否填 ""，而非省略字段？
        □ 检查7: 所有数据是否来自原图，未编造？
        □ 检查8: 设备位号是否与原图格式完全一致？
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
                "towers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tag": {"type": "string"},
                            "name": {"type": "string"},
                            "reflux_structure": {
                                "type": "object",
                                "properties": {
                                    "has_reflux": {"type": "boolean"},
                                    "reflux_type": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                            },
                            "reflux_detail": {
                                "type": ["object", "null"],
                                "properties": {
                                    "has_top_condenser": {"type": ["boolean", "null"]},
                                    "has_bottom_reboiler": {"type": ["boolean", "null"]},
                                    "top_condenser_tag": {"type": "string"},
                                    "bottom_reboiler_tag": {"type": "string"},
                                    "reflux_flow_rate": {
                                        "type": "object",
                                        "properties": {
                                            "value": {"type": ["number", "null"]},
                                            "unit": {"type": "string"},
                                        },
                                    },
                                },
                            },
                            "operating_conditions": {
                                "type": "object",
                                "properties": {
                                    "top_temperature": {
                                        "type": "object",
                                        "properties": {
                                            "value": {"type": ["number", "null"]},
                                            "unit": {"type": "string"},
                                        },
                                    },
                                    "top_pressure": {
                                        "type": "object",
                                        "properties": {
                                            "value": {"type": ["number", "null"]},
                                            "unit": {"type": "string"},
                                        },
                                    },
                                    "bottom_temperature": {
                                        "type": "object",
                                        "properties": {
                                            "value": {"type": ["number", "null"]},
                                            "unit": {"type": "string"},
                                        },
                                    },
                                    "bottom_pressure": {
                                        "type": "object",
                                        "properties": {
                                            "value": {"type": ["number", "null"]},
                                            "unit": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        },
                        "required": ["tag"],
                    },
                },
                "reactors": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tag": {"type": "string"},
                            "name": {"type": "string"},
                            "reflux_structure": {
                                "type": "object",
                                "properties": {
                                    "has_reflux": {"type": "boolean"},
                                    "reflux_type": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                            },
                            "operating_conditions": {
                                "type": "object",
                                "properties": {
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
                                },
                            },
                        },
                        "required": ["tag"],
                    },
                },
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["towers", "reactors"],
        }
