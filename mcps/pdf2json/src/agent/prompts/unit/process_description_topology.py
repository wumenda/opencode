from __future__ import annotations

from typing import Any

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt


@register_prompt("process_description_topology", "v1")
class ProcessDescriptionTopologyPromptBuilderV1(PromptBuilder):
    """从工艺流程说明文本中提取主工艺设备之间的连接拓扑。"""

    expert_type = "process_description_topology"
    version = "v1"
    description = "工艺说明文档拓扑提取（纯文本输入）"

    _ROLE = """\
        【角色】
        你是化工工艺流程分析专家。你的任务是：阅读工艺流程说明文档，从中提取出主工艺流程设备（equipment）及其之间的物料连接关系（connection）。

        【分析对象】
        工艺流程说明文档是一段自然语言文本，描述了化工装置中物料的流向、设备的操作条件和工艺目的。
        文档中会以"设备中文名称+位号"的形式提及各设备，如"异丁烯缓冲罐V-81001""二聚反应器R-81001""异丁烯回收塔T-81001"等。
        """

    _EQUIPMENT_RULES = """\
        【设备（equipment）提取规则】
        1. 提取文档中所有具有标准位号的工艺设备作为 equipment 节点。
        2. 标准位号前缀：V（容器/罐）、T（塔器）、R（反应器）、E（换热器/冷却器/冷凝器）、P（泵）、FL（过滤器）、M（混合器）等。
        3. 每个设备必须输出：
           - id: 格式 equip_N（如 equip_1, equip_2），按文档首次出现顺序编号
           - name: 设备中文名称（如"异丁烯缓冲罐"）
           - tag: 设备位号（如"V-81001"）
        4. 如果文档中多次提到同一设备（如同一位号出现在不同段落），只输出一个 equipment 节点。
        5. 泵（P-XXX）和过滤器（FL-XXX）属于输送/辅助设备，如果它们只是管线中间的过渡设备（不改变物料组成、不做分离/反应），不应作为独立 equipment 节点，而应在 connection 的 description 中提及。
        6. 储罐/缓冲罐/回流罐/收集罐（V-XXX）如果作为物料的中间存储或缓冲节点，应作为独立 equipment 节点输出。
        """

    _CONNECTION_RULES = """\
        【连接关系（connection）提取规则】
        1. 从文档的物料流向描述中提取设备间的连接关系。每条 connection 表示一股物料从源设备流向目标设备。
        2. 每条 connection 必须输出：
           - source: 源设备的 equipment id（物料流出的设备）
           - target: 目标设备的 equipment id（物料流入的设备）
           - material_name: 物料/介质名称（如"异丁烯""二聚反应原料""反应产物""塔顶出料"等）
           - description: 简要说明该连接的工艺含义（如"新鲜异丁烯由界外送入异丁烯缓冲罐储存"）
        3. 物料流向判断依据：
           - "A进入B""A送入B""A输送至B" → source=A, target=B
           - "A出料进入B""A塔釜出料由泵输送至B" → source=A, target=B
           - "A采出进入B""A塔顶采出至B" → source=A, target=B
           - "A返回B" → source=A, target=B
           - "B由A进料""B以A为进料" → source=A, target=B
        4. 如果物料从界外（系统外）进入某设备，source 填 "external"（表示界外）。
        5. 如果物料输出至界外（如"输送至界外""送往RTO处理"），target 填 "external"。
        6. 循环回路（如"反应产物一部分循环返回反应器入口"）也要输出为 connection，source 和 target 可以是同一设备或不同设备。
        7. 多股不同物料从同一设备进入另一设备时，分别输出多条 connection。
        8. 同一股物料经过多个设备串联时，每段都要输出为独立的 connection（如 A→B→C 应输出 A→B 和 B→C 两条）。
        9. 只提取文档中明确描述的连接关系，不要根据设备类型或常识推断未提及的连接。
        """

    _OUTPUT_FORMAT = """\
        【输出要求】
        直接输出纯 JSON，不要输出 markdown，不要输出解释文字。

        {
          "document_name": "工艺流程说明",
          "equipment": [
            {
              "id": "equip_1",
              "name": "异丁烯缓冲罐",
              "tag": "V-81001"
            },
            {
              "id": "equip_2",
              "name": "二聚反应器",
              "tag": "R-81001"
            }
          ],
          "connections": [
            {
              "source": "external",
              "target": "equip_1",
              "material_name": "异丁烯",
              "description": "新鲜反应原料异丁烯自界外送入异丁烯缓冲罐V-81001储存"
            },
            {
              "source": "equip_1",
              "target": "equip_2",
              "material_name": "异丁烯",
              "description": "异丁烯由泵P-81001输送至二聚原料缓冲罐配置反应原料后进入二聚反应器"
            }
          ],
          "warnings": []
        }
        """

    _MANDATORY_CHECK = """\
        【强制自检 — 输出前逐项执行】
        □ 检查1: 所有 equipment 的 id 是否唯一且格式为 equip_N？
        □ 检查2: 所有 equipment 的 tag 是否与文档原文一致，没有编造？
        □ 检查3: 所有 connection 的 source/target 是否引用了存在的 equipment id（或 "external"）？
        □ 检查4: 是否有遗漏的物料流向（重新通读文档确认每段流向都已被提取）？
        □ 检查5: 泵/过滤器等过渡设备是否已被排除出 equipment 列表（除非它们是独立分离/反应节点）？
        □ 检查6: 循环回路是否已提取为 connection？
        □ 检查7: source 和 target 方向是否正确（物料从 source 流向 target）？
        """

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]

        if context.has_process_description:
            sections.append(
                self.build_process_description_section(context.process_description)
            )

        sections.extend(
            [
                self._EQUIPMENT_RULES,
                self._CONNECTION_RULES,
                self._OUTPUT_FORMAT,
                self._MANDATORY_CHECK,
            ]
        )

        return "\n".join(section for section in sections if section)

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["equipment", "connections"],
            "properties": {
                "document_name": {"type": "string"},
                "equipment": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "name", "tag"],
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "tag": {"type": "string"},
                        },
                    },
                },
                "connections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "source",
                            "target",
                            "material_name",
                            "description",
                        ],
                        "properties": {
                            "source": {"type": "string"},
                            "target": {"type": "string"},
                            "material_name": {"type": "string"},
                            "description": {"type": "string"},
                        },
                    },
                },
                "warnings": {"type": "array"},
            },
        }
