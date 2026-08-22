from __future__ import annotations

from typing import Any

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt


@register_prompt("plant_unit_topology_one_by_one", "v1")
class PlantUnitTopologyOneByOnePromptBuilderV1(PromptBuilder):
    expert_type = "plant_unit_topology_one_by_one"
    version = "v1"
    description = "Whole-plant unit product outlet extraction for one focused unit"

    _ROLE = """
      你是全厂级装置产物去向提取专家。当前只处理一个装置的外送物流，不能试图一次性完成整张图。
      你会收到原始图片、全部装置列表和文字去向节点列表，以及本轮 current_unit。
      本轮目标是：找出从 current_unit 输出的每条产物/物料流的去向——即进入了哪些装置或文字去向节点。
      """

    _CONTEXT = """
      【本轮进度】
      unit_index: {unit_index}
      unit_count: {unit_count}

      【current_unit】
      {current_unit_context}

      【全部装置列表】
      {plant_unit_context}

      【文字去向节点列表】
      {text_destination_context}
      """

    _RULES = """
      【单装置产物去向规则】
      1. 当前只处理一个装置：只输出 current_unit 的产物去向，不要输出其他装置的产物信息。
      2. 禁止输出其他装置输入 current_unit 的流股；只关注 current_unit 发出的产物。
      3. 禁止输出其他装置之间的产物去向，即使它们在图上很清楚，也不属于本轮任务。
      4. 只有当 current_unit 的出口线、出口箭头或右侧产物箭头明确进入另一个 plant_unit 或 text_destination 节点时，才记录该产物去向。
      5. target 中的 id 必须来自【全部装置列表】中的某个节点 id，可以是装置节点也可以是文字去向节点。
      6. material_name 使用 current_unit 出口线、出口箭头旁、框右侧产物列表或同一条连线上可见的物料名称。
      7. 箭头方向是最高优先级证据：箭头头部指向哪里，物料就流向哪里；箭头头部进入或贴近的节点才是 target。
      8. 如果同一产物从 current_unit 分别进入多个下游节点，target 列表包含所有下游节点 id，不要拆成多条 product_outlet。
      9. 如果 current_unit 的多个不同产物进入同一个下游装置，必须为每个产物分别输出 product_outlet；不要把多个 material_name 合并到一条记录里，也不要因为 target 相同而漏掉后续产物。
      10. 如果只能看到流股进入 current_unit，或方向证据表明箭头头部指向 current_unit，必须忽略。
      11. 如果方向不清、无法确认是 current_unit 发出，宁可不输出；可在 warnings 说明不确定连接。
      12. 若 current_unit 的某条线只外送到图外或没有连接任何节点，该产物的 target 留空数组。
      13. 若 current_unit 的某条出口箭头指向"去向A""去向B"等文字去向，target 填该文字去向节点的 id。

      【装置左右进出方向约束】
      1. 本类装置级流程图中，装置的入口全部在左侧，出口全部在右侧；current_unit 的左侧连接线按输入候选处理，右侧连接线按出口候选处理。
      2. 左侧连接线、左侧箭头或从左侧进入 current_unit 的管线通常是输入，禁止输出为 current_unit 的 product_outlet。
      3. 右侧连接线、右侧产物文字、从 current_unit 右侧离开的箭头/管线才是本轮重点出口候选；优先从 current_unit 右侧向外追踪 target。
      4. 如果右侧出口候选与箭头方向冲突，仍以箭头头部方向为最高优先级证据；冲突无法消解时宁可不输出，并在 warnings 说明。

      【箭头方向判定流程】
      1. 先找离 current_unit 出口线最近且同属该线的箭头，不要用左右位置或装置常识替代箭头方向。
      2. 箭头头部远离 current_unit：该线可能是 current_unit 的输出，继续沿箭头方向找下游 target。
      3. 箭头头部指向 current_unit：该线是 current_unit 的输入，必须跳过。
      4. 同一条折线或长线有多个箭头时，以当前追踪段最近、同属该段的箭头为准；每个分叉支路要重新确认该支路上的箭头方向。
      5. 若没有箭头但线从 current_unit 右侧产物标签直接延伸到某节点，可作为低置信出口；若存在任何反向箭头证据，则以箭头为准并忽略。

      【务必找全的逐项检查流程】
      1. 先把 current_unit_context 中的 products、bbox/position、name/unit_name/unit_trains 当作本轮出口核对清单。
      2. 先扫描 current_unit 右侧所有离开该装置的出口线、出口箭头、右侧产物文字，再核对左侧是否仅为输入线；不要只看最明显的一条线，也不要只找一个下游装置就停止。
      3. 对每一个右侧出口候选，沿着线段和箭头从 current_unit 向外追踪到底：遇到折线继续跟踪，遇到分叉要分别跟踪每个分支，直到进入某个装置框、指向文字去向节点、出图外或证据中断。
      4. 如果同一产物从 current_unit 进入多个下游节点，target 列表必须包含所有下游节点 id。
      5. 如果多个产物进入同一个下游节点，逐个产物核对并逐条输出；target 相同不是去重理由，material_name 不同就必须保留。
      6. 如果 current_unit 的 products 中某个产物在图上有对应出口箭头或连线，必须尝试追踪其去向；未找到去向时，该产物 target 留空数组并在 warnings 中说明。
      7. 最终输出前自检：product_outlets 是否覆盖了 current_unit 所有可见出口物流及其全部下游节点分支；是否错误包含了任何输入 current_unit 的流股；是否因为多个产物共享同一个 target 而漏输出。
      """

    _OUTPUT = """
      【输出要求】
      直接输出纯 JSON，不要输出 markdown，不要输出解释文字。

      {
        "current_unit_id": "unit_001",
        "plant_unit_topology_one_by_one": [
          {
            "material_name": "物料A",
            "target": ["unit_002"]
          },
          {
            "material_name": "物料B",
            "target": ["dest_001"]
          }
        ],
        "warnings": []
      }
      """

    def build(self, context: PromptContext) -> str:
        unit_context = context.extra.get("plant_unit_context", "")
        current_unit_context = context.extra.get("current_unit_context", "")
        text_destination_context = context.extra.get("text_destination_context", "")
        unit_index = context.extra.get("unit_index", "")
        unit_count = context.extra.get("unit_count", "")
        sections = [self._ROLE]
        if context.has_image_size:
            sections.append(self.build_image_size_section(context.image_size))
        sections.append(
            self._CONTEXT.format(
                unit_index=unit_index,
                unit_count=unit_count,
                current_unit_context=current_unit_context,
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
                "current_unit_id": {"type": "string"},
                "plant_unit_topology_one_by_one": {"type": "array"},
                "warnings": {"type": "array"},
            },
            "required": ["current_unit_id", "plant_unit_topology_one_by_one"],
        }
