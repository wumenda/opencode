from __future__ import annotations

from typing import Any

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt


@register_prompt("plant_unit_topology", "v1")
class PlantUnitTopologyPromptBuilderV1(PromptBuilder):
    expert_type = "plant_unit_topology"
    version = "v1"
    description = "Whole-plant unit topology extraction"

    _ROLE = """
      你是全厂级装置产物去向提取专家。你会收到原始流程图图片，以及装置提取专家给出的装置节点列表和文字去向节点列表。
      任务是针对每个装置节点，提取其产物/外送物料的去向——即每条产物线最终进入了哪个装置或文字去向节点。
      """

    _CONTEXT = """
      【装置节点列表】
      {plant_unit_context}

      【文字去向节点列表】
      {text_destination_context}
      """

    _RULES = """
      【产物去向提取规则】
      1. 对每个装置节点，沿其出口箭头和连接线追踪产物去向；必须先判断箭头方向，再判断 source/target。
      2. 箭头头部指向的方向就是物料流向，箭头头部落入或贴近的装置/文字去向才是 target；箭头尾部连接的装置才可能是发出该产物的 source。
      3. 如果线段几何上连接两个装置，但最近且同属该线段的箭头指向当前装置，则该线是当前装置的输入，不能作为当前装置 product_outlet。
      4. 每条产物线对应一个 product_outlet，material_name 是该产物/物料名称，target 是该产物最终进入的装置节点 id 或文字去向节点 id 列表。
      5. 一个装置的多个不同产物可以进入同一个下游装置：必须分别输出多个 product_outlet，不要因为 target 相同而合并 material_name。
      6. 一个装置的同一个产物可以分叉进入多个下游装置或文字去向：只输出一个 product_outlet，并把全部下游节点 id 放入同一个 target 列表。
      7. 分叉线必须逐支路追踪；每个分支都要继续按箭头头部方向确认最终进入的是哪个装置或文字去向。
      8. 如果箭头指向"去向A""去向B""去向C"等文字去向，target 填该文字去向节点的 id。
      9. 一条线经过中间装置时，该产物线属于发出它的装置，不属于中间装置；中间装置有自己的产物线。
      10. 没有可见箭头或连线证据时不要臆造产物去向；方向证据冲突时宁可 target 留空并在 warnings 说明。
      11. 如果某产物的去向无法追踪到任何已知节点，target 可留空数组，但不要省略该 product_outlet。

      【装置左右进出方向约束】
      1. 本类装置级流程图中，装置的入口全部在左侧，出口全部在右侧；先用该版式约束区分输入候选和输出候选。
      2. 左侧连接线、左侧箭头或从左侧进入装置框的管线通常是该装置输入，不能作为该装置的 product_outlet。
      3. 右侧连接线、右侧产物文字、从装置框右侧离开的箭头/管线才是该装置出口候选，应优先从右侧向外追踪 target。
      4. 如果右侧出口候选与箭头方向冲突，仍以箭头头部方向为最高优先级证据；冲突无法消解时不要臆造 target，并在 warnings 说明。

      【全图核对流程】
      1. 先逐个装置读取 products 作为出口清单，但不要仅凭清单猜下游，必须回到图上找对应箭头/连线。
      2. 对每个产物名，重点在该装置框右侧、右侧产物箭头和右侧邻近出口线附近寻找同名或相邻标签；从标签对应的右侧线段开始追踪。
      3. 沿线追踪时遇到折线、跨线、汇合、分叉都不能提前停止；只有当箭头头部进入/指向某个已知节点、出图外或线证据中断时才停止。
      4. 输出前按 "source unit + material_name" 检查：同一 material_name 的多个 target 是否都在同一条记录中；不同 material_name 即使 target 相同也是否分别保留。
      """

    _OUTPUT = """
      【输出要求】
      直接输出纯 JSON，不要输出 markdown，不要输出解释文字。

      {
        "drawing_id": "plant_unit_drawing_1",
        "drawing_name": "全厂总加工流程",
        "units": [
          {
            "id": "unit_001",
            "product_outlets": [
              {
                "material_name": "物料A",
                "target": ["unit_002"]
              },
              {
                "material_name": "物料B",
                "target": ["dest_001"]
              }
            ]
          },
          {
            "id": "unit_002",
            "product_outlets": [
              {
                "material_name": "物料C",
                "target": ["unit_003"]
              }
            ]
          }
        ],
        "warnings": []
      }
      """

    def build(self, context: PromptContext) -> str:
        unit_context = context.extra.get("plant_unit_context", "")
        text_destination_context = context.extra.get("text_destination_context", "")
        sections = [self._ROLE]
        if context.has_image_size:
            sections.append(self.build_image_size_section(context.image_size))
        if unit_context:
            sections.append(
                self._CONTEXT.format(
                    plant_unit_context=unit_context,
                    text_destination_context=text_destination_context,
                )
            )
        sections.extend([self._RULES, self._OUTPUT])
        return "\n".join(section for section in sections if section)

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "drawing_id": {"type": "string"},
                "drawing_name": {"type": "string"},
                "units": {"type": "array"},
                "warnings": {"type": "array"},
            },
            "required": ["units"],
        }
