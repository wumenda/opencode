from __future__ import annotations

from typing import Any

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt


@register_prompt("plant_unit_general", "v1")
class PlantUnitGeneralPromptBuilderV1(PromptBuilder):
    expert_type = "plant_unit"
    version = "v1"
    description = "Whole-plant unit node extraction for general plant-wide process flow diagrams"

    _ROLE = """
      你是全厂级加工流程图的装置节点提取专家。图中矩形框表示装置、系统、处理单元或装置组合，
      矩形左侧通常列出该装置的输入物料/进料，矩形右侧通常列出该装置的产物/外送物料；
      输入物料不是独立拓扑节点，应写入装置节点 feeds/feed_inlets 字段；产物不是独立拓扑节点，
      应写入装置节点 products/product_outlets 字段。全厂总加工流程图中的数字表格也属于装置节点信息：
      输入侧物料要记录名称和输入数量，输入要求表要记录 API、硫含量、酸值等组分/性质要求；
      产物侧物料要记录名称、占总产物百分比和产物数量。
      """

    _UNIT_DEFINITION = """
      【装置节点的视觉定义】
      装置节点必须是图中一个完整封闭矩形外框包围的方框/长方框，框内通常包含：
      - 装置主名称，例如"示例装置A""示例装置B""示例装置C"；
      - 可选的子装置、系列号或说明文字，例如"3#示例装置A""1#示例装置C/2#示例装置C/3#示例装置C"；
      - 左侧或上下游有箭头/管线接入（接入的物料为输入物料/进料），右侧常有一个或多个物料箭头引出（引出的物料为产物）。

      判框时必须取外层矩形框的范围作为 bbox，不要只框中文字，也不要把右侧箭头和物料文字包含进 bbox。


      【框内名称结构】
      装置框内文字有三种常见形态，必须在模型字段里区分：
      1. 有总装置名 + 多套子装置：例如框内上方是"示例装置C"，下方是"1#示例装置C""2#示例装置C""3#示例装置C"。
        - name/display 用"示例装置C"
        - unit_name 用"示例装置C"
        - unit_trains 用 ["1#示例装置C", "2#示例装置C", "3#示例装置C"]
      2. 没有总装置名，只有子装置名：例如"1#示例装置D（停）""2#示例装置D"。
        - unit_name 为空字符串
        - unit_trains 逐条记录这些子装置文字
        - name 用 unit_trains 合并后的可读名称，例如"1#示例装置D / 2#示例装置D"
      3. 只有一个装置名，没有 # 子项：例如"示例装置E"。
        - name 和 unit_name 都用"示例装置E"
        - unit_trains 为空数组

      【连体/无名装置框】
      如果某个小矩形或细长框与主装置框上下相连、共享边界或明显作为主装置附近的处理段出现，
      仍然把它当作一个普通装置节点输出到 plant_unit 数组，不要使用单独的辅助单元字段：
      - node_type 使用 "plant_unit"；
      - 如果框内没有可见名称，name 和 unit_name 可为空字符串；
      - bbox/position 定位该无名框本身；
      - metadata.visible_text 可为空字符串，metadata.evidence 写明它与哪个主装置相连。
      """

    _TEXT_DESTINATION = """
      【文字去向节点】
      装置出口箭头有时不进入另一个装置方框，而是直接指向一段文字，例如"去向A""去向B""去向C"。
      这些文字表示该物料的去向，它们不是装置，但应作为独立节点提取，node_type 设为 "text_destination"。
      - name 填写图上可见的去向文字，例如"去向A""去向B"；
      - id 以 "dest_" 开头，例如 "dest_001"；
      - bbox 和 position 定位该文字在图上的位置；
      - products 为空数组。

      如果同一个去向文字在图上多处出现且明显是同一个去向（例如多处"去向A"），只提取一个节点。
      如果"去向A"和"去向D"是不同文字，分别提取为不同节点。
      """

    _BBOX_RULES = """
      【bbox 定位规则】
      目标是定位装置方框本身的外层闭合矩形边界，而不是定位文字区域。

      逐步执行：
      1. 先沿黑色矩形边线定位装置框的左、右、上、下四条外边；bbox=[x1,y1,x2,y2] 必须贴住这些外边。
      2. 不要框文字：框内文字的宽高通常小于装置外框，不能用文字块当 bbox。
      3. 如果装置名称位于黄底竖向窄条内，bbox 必须框住该黄底竖条的外边界；如果是白底黑边竖条，bbox 必须框住该黑边竖条。
      4. bbox 不能落在装置条左侧或右侧的空白列；如果 bbox 内几乎没有黑线、黄底或装置文字，说明坐标错误，必须移动到可见装置条上。
      5. 不要包含出口箭头、入口箭头、左侧输入物料文字、右侧产品文字、连接线、相邻装置框；bbox 只覆盖该装置外框。
      6. 对细长竖向装置框，要包含完整上边和下边，不要只截取中间文字区域。
      7. 对有多行子装置名的方框，要覆盖完整外框高度，不要按某一行子装置文字裁剪。
      8. 对与主装置连成一体的无名框，也要定位该无名框自己的矩形外框；如果它与主装置共享边界，bbox 贴住该附属框可见外边，不并入主装置。
      9. 当外框边线被管线遮挡或贴近其他线条时，优先根据可见的闭合矩形四角和对边延长来估计外框，宁可贴边略紧，也不要向外扩到管线/箭头文字。
      10. position 使用 bbox 中心点，不使用文字中心点。
      11. 如果 bbox 有不确定性，在 metadata.bbox_quality 中写入 "high" | "medium" | "low"，并在 metadata.bbox_evidence 说明依据。

      常见错误：
      - 错误：bbox 只包住"示例装置C/1#示例装置C/2#示例装置C/3#示例装置C"的文字。
      - 正确：bbox 包住这些文字外面的整个细长矩形装置框。
      - 错误：bbox 把左侧"进料A"输入物料文字或右侧"产物C""产物D"产物箭头文字一起包进去。
      - 正确：输入物料名进入 feeds，产物名进入 products，都不进入 bbox。
      - 错误：bbox 落在黄底竖条左边的空白列，虽然 y 范围接近，但 x 位置没有覆盖装置条。
      - 正确：bbox 贴住黄底或白底黑边装置条本身。
    """

    _RULES = """
      【提取规则】
      1. 只提取带完整封闭矩形外框的装置/系统/处理单元方框；没有外框的物料名、箭头标签、页码、图例、线段、管线转角都不是装置节点。
      2. 每个装置节点必须包含 id、name、unit_name、unit_trains、feeds、products、bbox、position。
      3. name 取框内主装置名称；如果框内有主名称和子项，主名称优先，例如"示例装置A"。
      4. feeds 只记录该装置框左侧、入口箭头旁或框内明确对应的输入物料/进料名称；不要把 feeds 里的文字再作为 plant_units。
      5. feed_inlets 是 feeds 的结构化版本，每项必须包含 material_name；如果该输入旁有数量数值，填 quantity；没有单位时 quantity_unit 留空。
      6. feed_requirements 记录该装置对输入物料的组分/性质要求，例如 API、硫含量、酸值；这些不是物料，也不是产物。
      7. products 只记录该装置框右侧、出口箭头旁或框内明确对应的产物/输出物料名称；不要把 products 里的文字再作为 plant_units。
      8. product_outlets 是 products 的结构化版本，每项必须包含 material_name；如果右侧表格有产物占比，填 share_percent；如果有产物数量，填 quantity。
      9. 对图中合计行，除非它是明确物料名称，不要作为 feed_inlets/product_outlets 的物料项。
      10. 如果装置框内列出子装置或系列（如 1#、2#、3#），优先把外层框作为一个装置节点，并把子项放入 unit_trains；不要把每个 1#/2#/3# 子装置拆成独立 plant_unit。
      11. 对细长竖框也要识别为装置，只要它有完整矩形外框和框内装置名称；不要因为框窄或文字少而漏检。
      12. 对与主装置连成一体的无名框，也作为独立 plant_unit 输出；name/unit_name 可为空，metadata 说明依据。
      13. bbox 和 position 必须使用归一化坐标，范围 0.0 到 1.0。
      14. name 使用图上可见中文名称，不要自行翻译或补全。
      15. 文字去向（如"去向A""去向B""去向C"）提取为 node_type="text_destination" 的独立节点，放入 text_destinations 数组。
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
            "name": "示例装置C",
            "unit_name": "示例装置C",
            "unit_trains": ["1#示例装置C", "2#示例装置C", "3#示例装置C"],
            "feeds": ["进料C", "进料D"],
            "feed_inlets": [
              {"material_name": "进料C", "quantity": 100.0, "quantity_unit": ""},
              {"material_name": "进料D", "quantity": 100.0, "quantity_unit": ""}
            ],
            "feed_requirements": [
              {"property_name": "API", "value": 30.00, "unit": "", "applies_to": ["进料C", "进料D"], "raw_text": "API 30.00"},
              {"property_name": "硫含量", "value": 1.0000, "unit": "wt%", "applies_to": ["进料C", "进料D"], "raw_text": "硫含量 wt% 1.0000"}
            ],
            "products": ["产物E", "产物F"],
            "product_outlets": [
              {"material_name": "产物E", "share_percent": 10.00, "quantity": 20.00, "quantity_unit": "", "raw_text": ""},
              {"material_name": "产物F", "share_percent": 15.00, "quantity": 30.00, "quantity_unit": "", "raw_text": ""}
            ],
            "bbox": [0.10, 0.30, 0.15, 0.42],
            "position": [0.125, 0.36],
            "aliases": [],
            "metadata": {
              "visible_text": "框内可见文字",
              "bbox_quality": "high",
              "bbox_evidence": "bbox 贴合装置外层闭合矩形四条边，未包含右侧产品箭头"
            }
          }
        ],
        "text_destinations": [
          {
            "id": "dest_001",
            "node_type": "text_destination",
            "name": "去向A",
            "bbox": [0.18, 0.34, 0.20, 0.36],
            "position": [0.19, 0.35]
          },
          {
            "id": "dest_002",
            "node_type": "text_destination",
            "name": "去向B",
            "bbox": [0.18, 0.38, 0.22, 0.40],
            "position": [0.20, 0.39]
          }
        ],
        "warnings": []
      }
      """

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]
        if context.has_image_size:
            sections.append(self.build_image_size_section(context.image_size))
        sections.extend(
            [
                self._UNIT_DEFINITION,
                self._TEXT_DESTINATION,
                self._BBOX_RULES,
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


@register_prompt("plant_unit_general", "v2")
class PlantUnitGeneralPromptBuilderV2(PromptBuilder):
    expert_type = "plant_unit"
    version = "v2"
    description = " (role + goal + output schema only)"

    _ROLE = """
      你是全厂级加工流程图的装置节点提取专家。

      目标：从全厂级加工流程图中提取装置节点及其输入物料与产物信息。
      - 图中矩形框表示装置、系统、处理单元或装置组合；
      - 矩形左侧通常列出该装置的输入物料/进料，矩形右侧通常列出该装置的产物/外送物料；
      - 输入物料写入装置节点 feeds/feed_inlets 字段，产物写入 products/product_outlets 字段；
      - 输入物料的组分/性质要求（如 API、硫含量、酸值）写入 feed_requirements；
      - 装置出口箭头指向的"去向X"等文字提取为独立的 text_destination 节点。

      你自行判断如何识别装置、如何定位 bbox、如何区分装置名/子装置/物料/产物/去向文字，
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
            "name": "示例装置C",
            "unit_name": "示例装置C",
            "unit_trains": ["1#示例装置C", "2#示例装置C", "3#示例装置C"],
            "feeds": ["进料C", "进料D"],
            "feed_inlets": [
              {"material_name": "进料C", "quantity": 100.0, "quantity_unit": ""},
              {"material_name": "进料D", "quantity": 100.0, "quantity_unit": ""}
            ],
            "feed_requirements": [
              {"property_name": "API", "value": 30.00, "unit": "", "applies_to": ["进料C", "进料D"], "raw_text": "API 30.00"},
              {"property_name": "硫含量", "value": 1.0000, "unit": "wt%", "applies_to": ["进料C", "进料D"], "raw_text": "硫含量 wt% 1.0000"}
            ],
            "products": ["产物E", "产物F"],
            "product_outlets": [
              {"material_name": "产物E", "share_percent": 10.00, "quantity": 20.00, "quantity_unit": "", "raw_text": ""},
              {"material_name": "产物F", "share_percent": 15.00, "quantity": 30.00, "quantity_unit": "", "raw_text": ""}
            ],
            "bbox": [0.10, 0.30, 0.15, 0.42],
            "position": [0.125, 0.36],
            "aliases": [],
            "metadata": {
              "visible_text": "框内可见文字",
              "bbox_quality": "high",
              "bbox_evidence": "bbox 贴合装置外层闭合矩形四条边，未包含右侧产品箭头"
            }
          }
        ],
        "text_destinations": [
          {
            "id": "dest_001",
            "node_type": "text_destination",
            "name": "去向A",
            "bbox": [0.18, 0.34, 0.20, 0.36],
            "position": [0.19, 0.35]
          },
          {
            "id": "dest_002",
            "node_type": "text_destination",
            "name": "去向B",
            "bbox": [0.18, 0.38, 0.22, 0.40],
            "position": [0.20, 0.39]
          }
        ],
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
