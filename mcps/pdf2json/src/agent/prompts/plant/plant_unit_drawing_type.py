from __future__ import annotations

from typing import Any

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt


@register_prompt("plant_unit_drawing_type", "v1")
class PlantUnitDrawingTypePromptBuilderV1(PromptBuilder):
    expert_type = "plant_unit_drawing_type"
    version = "v1"
    description = "全厂装置图纸类型判别：通用(有管线连接) / 密集(物料表无管线) / unknown"

    _ROLE = """
    你是全厂级加工流程图的图纸类型判别专家。你的任务是判别输入的全厂装置流程图属于哪种类型：
    - plant_unit_general（通用型）：装置之间通过可见的箭头/折线/管线直接连接表示拓扑关系。
    - plant_unit_dense（密集型）：装置为竖向窄矩形条，仅通过左右两侧的物料名+数量表表示输入输出，装置之间无连线，靠物料名同名匹配推断流向。
    - unknown（无法判断）：图中既无装置间连线，也无清晰的物料表，或两类特征并存无法确定主类型。
    """

    _RULES = """
    【判别依据】
    1. plant_unit_general（通用型）的典型视觉特征：
       - 装置框（矩形）之间有可见的箭头、折线、管线直接连接。
       - 装置出口箭头从一侧引出，指向下游装置框或"去向X"等文字标签。
       - 装置框形状多样（横向矩形、方块等），框内可能有装置名+子装置。
       - 拓扑关系通过可见连线表达，物料名常标注在连线旁。
    2. plant_unit_dense（密集型）的典型视觉特征：
       - 装置呈竖向窄矩形条（黄色填充或白底黑边），条内写装置名称和规模数字。
       - 装置条左右两侧是物料名+数量+占比的表格，无装置间连线。
       - 装置密集排列，整图常有"全厂物料平衡表"汇总。
       - 拓扑关系靠左右物料表同名匹配推断，图面无箭头连接装置。
    3. 判别优先级：
       - 最高优先级：是否存在装置间的可见连线/箭头。有连线 → general；无连线但有物料表 → dense。
       - 其次：装置形态。竖向窄条 + 左右物料表 → dense；横向矩形 + 连线 → general。
       - 再次：图面布局。装置密集排列无连线 → dense；装置稀疏有连线 → general。
    4. 仅当图中既无装置间连线、也无清晰物料表，或两类特征并存无法确定主类型时，才输出 unknown。

    【总体原则】
    1. 只依据图中可见的视觉和文字信息判断，不要凭空推测。
    2. evidence 填写支持你判断的最短可复核证据，如"装置框之间有箭头连线指向下游装置"或"装置为竖向黄底窄条，左右为物料表，无装置间连线"。
    3. confidence 表示判断置信度（0.0-1.0）：特征清晰单一填1.0，需结合多处特征推断填0.6-0.9，信息不足填0.1-0.5。
    """

    _OUTPUT_FORMAT = """
    【输出要求】
    1. 仅输出 JSON，不要输出 markdown，不要解释。
    2. 顶层必须直接是下面的数据模型，所有字段必须存在。

    {
      "drawing_type": "plant_unit_general|plant_unit_dense|unknown",
      "evidence": "",
      "confidence": 0.0
    }
    """

    _CHECKLIST = """
    【自检清单】
    □ 是否只输出一个 JSON 对象
    □ drawing_type 是否仅取 plant_unit_general / plant_unit_dense / unknown 之一
    □ evidence 是否引用了图中具体的视觉证据（连线/箭头/装置形态/物料表）
    □ confidence 是否在 0.0-1.0 范围内
    """

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]
        if context.has_image_size:
            sections.append(self.build_image_size_section(context.image_size))
        sections.extend([self._RULES, self._OUTPUT_FORMAT, self._CHECKLIST])
        return "\n".join(s for s in sections if s)

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["drawing_type", "evidence", "confidence"],
            "properties": {
                "drawing_type": {
                    "type": "string",
                    "enum": ["plant_unit_general", "plant_unit_dense", "unknown"],
                },
                "evidence": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        }
