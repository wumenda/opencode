from typing import Any

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt


@register_prompt("equipment_type", "v1")
class EquipmentTypePromptBuilderV1(PromptBuilder):
    expert_type = "equipment_type"
    version = "v1"
    description = "V1 设备装配图分类：判断图纸属于板式塔/填料塔/反应器"

    _ROLE = """
    你是一个专业的化工设备装配图识别专家。你的任务是判别输入的设备装配图属于哪种设备类型：
    - column_tray（板式塔）：内部构件为塔板/塔盘的塔设备。
    - column_packed（填料塔）：内部构件为填料床段的塔设备。
    - reactor（反应器）：反应器设备（含壳程/管程结构）。
    - unknown（无法判断）：图中缺少内部构件信息或无法确定。
    """

    _RULES = """
    【判别依据】
    1. 板式塔（column_tray）的典型视觉特征：
       - 主视图中有贯穿塔截面的水平线段，表示塔板/塔盘。
       - 标注有塔板号（如 1#、2#、60#…或 1、2…的连续编号）。
       - 标注有板间距（tray spacing）尺寸。
       - 可见降液管（downcomer）符号。
       - 明细表/设计数据表中出现"塔板""塔盘""浮阀""泡罩""筛孔"等字样。
    2. 填料塔（column_packed）的典型视觉特征：
       - 主视图中有用斜线、交叉线或网格填充的塔段，表示填料床。
       - 标注有填料规格（如"50mm 鲍尔环""Φ25 散堆填料""规整填料"等）。
       - 表格信息中一般会有“填料高度”字段信息。
       - 标注有填料段高度尺寸。
       - 可见液体分布器、液体再分布器、填料支撑栅板等符号。
       - 明细表/设计数据表中出现"填料""鲍尔环""拉西环""规整填料""丝网除沫器"等字样。
    3. 反应器（reactor）的典型视觉特征：
       - 图纸标题栏或设计数据表中设备名称含"反应器""反应釜""反应罐"等字样。
       - 设计基本数据表中出现"壳程""管程"两侧数据（介质/密度/温度/流向）。
       - 主视图具有壳程/管程结构特征（如管束、管板、折流板等）。
       - 存在 flow_pattern（流型：逆流/并流/错流）相关标注。
       - 设备位号以 R 开头（如 R-XXXX、RXXXX）。
    4. 判别优先级：
       - 优先以图纸标题栏/设计数据表中的设备名称和位号为准。
       - 其次以主视图中可见的内部构件符号（塔板水平线 / 填料填充图案 / 壳管程结构）为准。
       - 再次参考明细表/设计数据表中的构件名称。
    5. 仅当图中完全看不到设备类型信息时，才输出 unknown。

    【总体原则】
    1. 只依据图中可见的视觉和文字信息判断，不要凭空推测。
    2. evidence 填写支持你判断的最短可复核证据，如"标题栏设备名称为甲醇回收塔，主视图可见水平塔板线及塔板号1-20"或"设计数据表含壳程/管程两侧数据，设备位号R-5201"。
    3. confidence 表示判断置信度（0.0-1.0）：设备名称和构件清晰可见填1.0，需结合多项特征推断填0.6-0.9，信息不足填0.1-0.5。
    """

    _OUTPUT_FORMAT = """
    【输出要求】
    1. 仅输出 JSON，不要输出 markdown，不要解释。
    2. 顶层必须直接是下面的数据模型，所有字段必须存在。

    {
      "equipment_type": "column_tray|column_packed|reactor|unknown",
      "evidence": "",
      "confidence": 0.0
    }
    """

    _CHECKLIST = """
    【自检清单】
    □ 是否只输出一个 JSON 对象
    □ equipment_type 是否仅取 column_tray / column_packed / reactor / unknown 之一
    □ evidence 是否引用了图中具体的设备类型证据
    □ confidence 是否在 0.0-1.0 范围内
    """

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]
        if context.has_image_size:
            sections.append(self.build_image_size_section(context.image_size))
        source_id = ""
        if context.extra:
            source_id = str(
                context.extra.get("equipment_id")
                or context.extra.get("column_id")
                or context.extra.get("reactor_id")
                or context.extra.get("source_image_id")
                or context.extra.get("id")
                or ""
            ).strip()
        if source_id:
            sections.append(f"【任务上下文】\n当前图像对应的设备样本 id 为：{source_id}。")
        sections.extend([self._RULES, self._OUTPUT_FORMAT, self._CHECKLIST])
        return "\n".join(s for s in sections if s)

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["equipment_type", "evidence", "confidence"],
            "properties": {
                "equipment_type": {
                    "type": "string",
                    "enum": ["column_tray", "column_packed", "reactor", "unknown"],
                },
                "evidence": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        }
