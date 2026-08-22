from __future__ import annotations

from typing import Any

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt


@register_prompt("plant_unit_dense", "v1")
class PlantUnitDensePromptBuilderV1(PromptBuilder):
    expert_type = "plant_unit"
    version = "v1"
    description = "Whole-plant unit node extraction for dense plant-wide balance diagrams"

    _ROLE = """
      你是全厂总加工流程图的装置信息提取专家。图中装置是竖向窄矩形装置条（黄色填充或白底黑边），
      条内写有装置名称（如"1#示例装置A""示例装置B"），底部或中部可能写有规模数字
      （如"1000""3x260""标1000"）。装置条左侧是输入物料表，右侧是产物表。

      任务：装置条→plant_unit；输入物料表→feeds/feed_inlets；输入性质要求→feed_requirements；
      产物表→products/product_outlets。装置条内的规模数字写入 metadata.capacity_text，
      但 name/unit_name 必须使用装置名称。右侧"全厂物料平衡表"是汇总表，禁止从中提取装置或物料。
      """

    _ATTACHED_AUXILIARY_UNITS = """
      【附属装置/连体小框强制识别】
      主装置条正下方或正上方常有独立闭合小矩形框（可能白底、无名称、只含数字或空白），
      必须作为独立 plant_unit 输出，不能合并到主装置。
      1. 检查每个主装置的紧邻上下方是否有同宽的独立闭合竖框。
      2. name/unit_name 优先用框内可见文字；若无，按"{主装置名称}附属装置"补全。
      3. metadata.visible_text 记录框内数字/文字，metadata.evidence 说明其位置依据。
      """

    _UNIT_DEFINITION = """
      【装置节点视觉定义与框内名称结构】
      装置节点取完整封闭矩形外框，框内文字有三种形态：
      1. 有总装置名 + 子装置（如"示例装置C"下有"1#示例装置C""2#示例装置C"）：
         name/unit_name 用总装置名，unit_trains 列子装置。
      2. 只有子装置名（如"1#示例装置D""2#示例装置D"）：
         unit_name 为空，unit_trains 逐条记录，name 合并为"1#示例装置D / 2#示例装置D"。
      3. 单一装置名（如"示例装置E"）：name/unit_name 相同，unit_trains 为空。
      """

    _TEXT_DESTINATION = """
      【文字去向节点】
      装置出口箭头指向的文字（如"去向A""去向B""去向C"）提取为 node_type="text_destination" 的独立节点。
      id 以 "dest_" 开头，products 为空数组。同一去向文字多处出现时只提取一个节点。
      """

    _RULES = """
      【提取规则】
      1. 每个装置节点必须包含 id、name、unit_name、unit_trains、feeds、products。
      2. name 使用图上可见中文名称，竖排文字按从上到下、从左到右还原。
      3. feeds 只记录装置框左侧入口箭头旁的输入物料；products 只记录右侧出口箭头旁的产物。
      4. feed_inlets/product_outlets 是 feeds/products 的结构化版本，每项含 material_name；
         有数量填 quantity，有占比填 share_percent；target 先留空，raw_text 保留原始文字。
      5. 斜杠物料（如"1#/2#物料C"）按共享后缀展开为独立 material_name，raw_text 保留原文；
         只有一个数量格时 quantity 共用，warnings 注明合并行。
      6. feed_requirements 记录 API、硫含量、酸值等输入物料性质要求，非物料也非产物。
      7. 合计行、小计行、序号行、单位行不作文物料项。
      8. 子装置/系列（1#、2#、3#）放入 unit_trains，不拆成独立 plant_unit。
      9. 文字去向提取为 text_destinations 数组。
      """

    _OUTPUT = """
      【输出要求】
      直接输出纯 JSON，不要输出 markdown，不要输出解释文字。

      {
        "drawing_id": "plant_unit_drawing_1",
        "drawing_name": "全厂总加工流程",
        "plant_unit": [
          {
            "id": "unit_001",
            "node_type": "plant_unit",
            "name": "1#示例装置A",
            "unit_name": "1#示例装置A",
            "unit_trains": [],
            "feeds": ["进料A", "进料B", "物料C", "物料D"],
            "feed_inlets": [
              {"material_name": "进料A", "quantity": 100.0, "quantity_unit": "", "raw_text": "进料A 100.00"},
              {"material_name": "进料B", "quantity": 100.0, "quantity_unit": "", "raw_text": "进料B 100.00"},
              {"material_name": "物料C", "quantity": 50.0, "quantity_unit": "", "raw_text": "1#/2#物料C 50.00"},
              {"material_name": "物料D", "quantity": 50.0, "quantity_unit": "", "raw_text": "1#/2#物料C 50.00"}
            ],
            "feed_requirements": [
              {"property_name": "API", "value": 30.00, "unit": "", "applies_to": ["进料A", "进料B"], "raw_text": "API 30.00"}
            ],
            "products": ["产物A", "产物B", "产物C", "产物D"],
            "product_outlets": [
              {"material_name": "产物A", "share_percent": 1.00, "quantity": 2.00, "quantity_unit": "", "raw_text": "产物A 1.00% 2.00"},
              {"material_name": "产物B", "share_percent": 20.00, "quantity": 40.00, "quantity_unit": "", "raw_text": "产物B 20.00% 40.00"}
            ],
            "aliases": [],
            "metadata": {
              "visible_text": "1#示例装置A 1000",
              "capacity_text": "1000"
            }
          },
          {
            "id": "unit_002",
            "node_type": "plant_unit",
            "name": "1#示例装置A附属装置",
            "unit_name": "1#示例装置A附属装置",
            "unit_trains": [],
            "feeds": [],
            "feed_inlets": [],
            "feed_requirements": [],
            "products": [],
            "product_outlets": [],
            "aliases": [],
            "metadata": {
              "visible_text": "1000",
              "capacity_text": "1000",
              "attached_to": "unit_001",
              "evidence": "1#示例装置A正下方的独立白底闭合附属装置框"
            }
          }
        ],
        "text_destinations": [],
        "warnings": []
      }
      """

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]
        if context.has_image_size:
            sections.append(self.build_image_size_section(context.image_size))
        sections.extend(
            [
                self._ATTACHED_AUXILIARY_UNITS,
                self._UNIT_DEFINITION,
                self._TEXT_DESTINATION,
                self._RULES,
                self._OUTPUT,
            ]
        )
        return "\n".join(section for section in sections if section)

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "drawing_id": {"type": "string"},
                "drawing_name": {"type": "string"},
                "plant_unit": {"type": "array"},
                "text_destinations": {"type": "array"},
                "warnings": {"type": "array"},
            },
            "required": ["plant_unit"],
        }


@register_prompt("plant_unit_dense", "v2")
class PlantUnitDensePromptBuilderV2(PromptBuilder):
    expert_type = "plant_unit"
    version = "v2"
    description = " (role + goal + output schema only)"

    _ROLE = """
      你是全厂总加工流程图的装置信息提取专家。

      目标：从密集型全厂总加工流程图中提取装置节点及其输入物料与产物信息。
      - 图中装置是竖向窄矩形装置条（黄色填充或白底黑边），条内写有装置名称
        （如"1#示例装置A""示例装置B"），底部或中部可能写有规模数字（如"1000""3x260""标1000"）；
      - 装置条左侧是输入物料表，右侧是产物表；
      - 装置条→plant_unit；输入物料表→feeds/feed_inlets；输入性质要求→feed_requirements；
        产物表→products/product_outlets；
      - 装置条内的规模数字写入 metadata.capacity_text，但 name/unit_name 必须使用装置名称；
      - 主装置条紧邻上下方的独立闭合小框（附属装置/连体小框）也作为独立 plant_unit 输出；
      - 右侧"全厂物料平衡表"是汇总表，禁止从中提取装置或物料；
      - 装置出口箭头指向的"去向X"等文字提取为独立的 text_destination 节点。

      你自行判断如何识别装置条、附属框、子装置/系列、斜杠物料合并、产物占比与数量、去向文字，
      最终按下面的数据结构输出纯 JSON。
      """

    _OUTPUT = """
      【输出要求】
      直接输出纯 JSON，不要输出 markdown，不要输出解释文字。

      {
        "drawing_id": "plant_unit_drawing_1",
        "drawing_name": "全厂总加工流程",
        "plant_unit": [
          {
            "id": "unit_001",
            "node_type": "plant_unit",
            "name": "1#示例装置A",
            "unit_name": "1#示例装置A",
            "unit_trains": [],
            "feeds": ["进料A", "进料B", "物料C", "物料D"],
            "feed_inlets": [
              {"material_name": "进料A", "quantity": 100.0, "quantity_unit": "", "raw_text": "进料A 100.00"},
              {"material_name": "进料B", "quantity": 100.0, "quantity_unit": "", "raw_text": "进料B 100.00"},
              {"material_name": "物料C", "quantity": 50.0, "quantity_unit": "", "raw_text": "1#/2#物料C 50.00"},
              {"material_name": "物料D", "quantity": 50.0, "quantity_unit": "", "raw_text": "1#/2#物料C 50.00"}
            ],
            "feed_requirements": [
              {"property_name": "API", "value": 30.00, "unit": "", "applies_to": ["进料A", "进料B"], "raw_text": "API 30.00"}
            ],
            "products": ["产物A", "产物B", "产物C", "产物D"],
            "product_outlets": [
              {"material_name": "产物A", "share_percent": 1.00, "quantity": 2.00, "quantity_unit": "", "raw_text": "产物A 1.00% 2.00"},
              {"material_name": "产物B", "share_percent": 20.00, "quantity": 40.00, "quantity_unit": "", "raw_text": "产物B 20.00% 40.00"}
            ],
            "aliases": [],
            "metadata": {
              "visible_text": "1#示例装置A 1000",
              "capacity_text": "1000"
            }
          },
          {
            "id": "unit_002",
            "node_type": "plant_unit",
            "name": "1#示例装置A附属装置",
            "unit_name": "1#示例装置A附属装置",
            "unit_trains": [],
            "feeds": [],
            "feed_inlets": [],
            "feed_requirements": [],
            "products": [],
            "product_outlets": [],
            "aliases": [],
            "metadata": {
              "visible_text": "1000",
              "capacity_text": "1000",
              "attached_to": "unit_001",
              "evidence": "1#示例装置A正下方的独立白底闭合附属装置框"
            }
          }
        ],
        "text_destinations": [],
        "warnings": []
      }
      """

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]
        if context.has_image_size:
            sections.append(self.build_image_size_section(context.image_size))
        sections.append(self._OUTPUT)
        return "\n".join(section for section in sections if section)

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "drawing_id": {"type": "string"},
                "drawing_name": {"type": "string"},
                "plant_unit": {"type": "array"},
                "text_destinations": {"type": "array"},
                "warnings": {"type": "array"},
            },
            "required": ["plant_unit"],
        }
