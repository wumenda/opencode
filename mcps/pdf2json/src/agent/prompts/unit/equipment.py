from typing import Any

from src.core.models import EquipmentType

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt

# 从 EquipmentType 枚举动态获取设备类型值，避免硬编码
_EQUIPMENT_TYPE_VALUES: list[str] = [e.value for e in EquipmentType]
_EQUIPMENT_TYPE_TEXT_INLINE: str = " / ".join(_EQUIPMENT_TYPE_VALUES)


@register_prompt("equipment", "v1")
class EquipmentPromptBuilderV1(PromptBuilder):
    expert_type = "equipment"
    version = "v1"
    description = (
        "详细"
    )

    _ROLE = """\
        【角色】
        你是PFD设备识别专家。你的任务：从图中提取有标准位号+有可见符号主体的设备节点，并为每个设备识别其连接端口（含方向）。

        范围边界：
        - 你能识别：带标准位号（P-/E-/V-/T-/R-/C-XXX）的泵、换热器、容器、塔器、反应器、压缩机、分离器、过滤器、加热炉等标准设备符号
        - 你不能识别：阀门、仪表、管线、文字标注、边界节点（"至XXX"/"来自XXX"/"界区"/"系统"）
        """

    _RECOGNITION_FLOW = """\
        【识别决策流程】
        对每个候选图形，严格按以下顺序判断：

        Step 1 — 是否有标准设备位号？
          标准位号前缀：P- / E- / V- / T- / R- / C-（如 P-101、E-201A）
          ├─ 是 → 进入 Step 2
          └─ 否 → 丢弃（不要输出）

        Step 2 — 是否有可见的设备符号主体？
          设备符号：圆形（泵/换热器）、矩形（容器/储罐）、塔形（精馏塔）、反应器轮廓等
          ├─ 是 → 输出为 equipment，进入 Step 3 识别端口
          └─ 否 → 丢弃（不要输出）

        Step 3 — 排除边界节点
          如果图形带有"至XXX"、"来自XXX"、"界区"、"系统"等去向/来源说明文字
          → 这是 boundary_node，禁止输出为 equipment

        结论：只有同时满足"有位号"+"有符号主体"+"非边界节点"的图形，才能进入 equipment 列表。
        """

    _EXCLUSIONS = """\
        【排除清单 — 以下图形禁止输出为 equipment】
        1. 阀门（闸阀、截止阀、止回阀、安全阀等符号）
        2. 仪表（圆圈、仪表泡、控制阀）
        3. 纯文字标注（无位号、无标准设备符号，仅有中文说明）
        4. 边界节点（带"至/来自/界区/系统"说明的圆形/箭头框）
        5. 管线、弯头、三通、箭头
        6. 虚线控制框、信号线、仪表连线
        """

    _TAG_AND_TYPE = f"""\
        【设备位号与类型】
        位号格式：前缀-数字编号[后缀]，如 P-101、E-201A、V-305B
        标准前缀：P（泵）、E（换热器）、V（容器/储罐）、T（塔器）、R（反应器）、C（压缩机）、S（分离器）、F（过滤器）、H（加热炉）、M（混合器）

        equipment_type 只能使用以下枚举值：
        - {_EQUIPMENT_TYPE_TEXT_INLINE}
        """

    _BBOX_RULES = """\
        【bbox 标注规则】
        bbox = [x1, y1, x2, y2]，只框设备可见图形主体。

        必须包含：设备符号的可见轮廓和内部结构
        必须排除：位号文字、中文名称、下划线、功率/热负荷文字、介质文字、仪表、阀门、箭头、管线、虚线控制框

        特殊情形：
        - 设备主体被管线穿过 → bbox 仍以设备外轮廓为准，管线延伸到设备外的部分不属于 bbox
        - 符号很窄（如混合器）→ bbox 也应很窄，不要为了包含文字而放大
        """

    _PORT_RECOGNITION = """\
        【端口识别规则】
        端口是外部可见管线与设备外轮廓的真实接触点。

        输出条件（必须同时满足）：
        1. 能看到外部连续管线进入或离开设备符号
        2. 管线真实接触设备外轮廓（不是从旁边经过）
        3. 不是内部结构线、文字下划线、仪表线、喷嘴虚线
        4. 一般来说输入输出端口在相对位置，如若泵的输入端口在右侧，输出端口就在左侧，也有可能出现在顶部/底部，要看管线走向。

        端口字段：
        - id: {设备id}_in_N / {设备id}_out_N / {设备id}_unk_N（按方向确定）
        - direction: "input"（箭头朝向设备）/ "output"（箭头背离设备）/ "unknown"（方向不明）
        - category: "process"（工艺主物流）/ "utility"（公用工程），不确定时优先 "process"
        - orientation: "top" / "bottom" / "left" / "right" / "unknown"（端口在设备外轮廓上的方位）
        - channel: 内部通道标识
        - label: 端口标签，看不清时留空
        - position: [x, y]，贴近设备外轮廓与管线接触处

        多端口提醒：
        - 塔器、容器、换热器、反应器、混合器、分离器可能有多个端口，上/右/下/左都要检查
        - 同一真实连接点只输出一个端口；同一侧多个独立连接则分别输出
        """

    _PORT_DIRECTION = """\
        【端口方向判断 — 严格依据箭头】
        direction 只能取 "input" / "output" / "unknown"。

        判断流程（对每个端口逐一执行）：
        Step 1: 找到连接到该端口的外部管线
        Step 2: 沿管线寻找箭头符号（→、←、↑、↓、◀、▶、△等）
        Step 3: 判断箭头与设备的空间关系
          - 箭头指向设备 → 物流流入设备 → direction = "input"
          - 箭头背离设备 → 物流流出设备 → direction = "output"
        Step 4: 若该管线上无箭头，沿管线向远处追踪到相邻设备/边界节点，根据流程物料总体流向判断端口方向
        Step 5: 若均无法确定 → direction = "unknown"


        场景示例：
        - 管线在设备左侧，箭头→（向右指，朝向设备）→ input
        - 管线在设备右侧，箭头→（向右指，背离设备）→ output
        - 管线在设备左侧，箭头←（向左指，背离设备）→ output
        - 管线在设备右侧，箭头←（向左指，朝向设备）→ input

        禁止事项：
        - 禁止仅凭设备类型推断方向（如"泵左入右出"）
        - 禁止先定 id（含_in_/_out_）再凑方向
        - 禁止把端口移到箭头或管线远端来匹配方向
        - 方向不明时保留端口并输出 "unknown"
        """

    _PORT_ORIENTATION = """\
        【端口方位 orientation — 所有端口必填】
        每个端口都必须输出 orientation 字段，表示端口在设备外轮廓上的几何方位。
        取值：top / bottom / left / right / unknown。

        判定方法：
        以端口 position 相对设备 bbox 中心 (cx, cy) 的偏移方向为准：
          dx = 端口x - cx，dy = 端口y - cy
          - |dy| > |dx| 且 dy < 0 → "top"（端口在设备上侧）
          - |dy| > |dx| 且 dy > 0 → "bottom"（端口在设备下侧）
          - |dx| > |dy| 且 dx < 0 → "left"（端口在设备左侧）
          - |dx| > |dy| 且 dx > 0 → "right"（端口在设备右侧）
          - 无法判定 → "unknown"

        注意事项：
        - orientation 描述的是端口在设备外轮廓上的空间方位，与 direction（物流方向）无关。
        - 端口 position 必须贴近设备外轮廓，若 position 偏离外轮廓则 orientation 不可靠。
        - 塔器（distillation_column）为竖直结构，端口多在 top/bottom，侧面端口归 left/right。
        """

    _PORT_CHANNEL = """\
        【端口内部通道 channel — 所有端口必填】
        channel 用于表达"设备内部的物料通道归属"：同一 channel 的端口在设备内部连通，
        不同 channel 的端口在设备内部不连通（典型如换热器管程 vs 壳程）。
        这一字段为下游拓扑推理提供"哪个入口的物料必定从哪个出口流出"的硬约束。

        取值规则（字符串，本设备内部唯一）：
          - "c1" / "c2" / ...：本设备的第 N 个内部通道
          - ""（空字符串）：单端口设备、或暂无法判定时

        几何对位判定（默认规则，VLM 应优先使用）：
          1. 仅考虑同一设备的 input + output 端口集合。
          2. 按端口 position 在 bbox 上的几何方位归类：top / bottom / left / right
             （以端口坐标相对 bbox 中心的 dx, dy 主导方向判定）。
          3. 配对规则：
             - top ↔ bottom 的端口归入同一 channel（如 top_in 与 bottom_out → "c1"）
             - left ↔ right 的端口归入同一 channel（如 right_in 与 left_out → "c2"）
          4. 同侧多个端口（如左侧两个 input）：若工艺常识允许合流，则同 channel；否则分别编号。
          5. 同方位只有 input 或只有 output（无对位端口）：channel = ""。

        各设备类型默认行为（按内部物料流动语义分类）：

        A 类 — 通道隔离型（多通道，必须显式声明 channel）：
          - heat_exchanger / cooler / heater：≥ 2 个 channel；top↔bottom 一组、left↔right 一组
          - furnace：每根盘管独立 channel；燃料/烟气为 utility 类别；多盘管（≥4 个 process 端口）时必须声明 channel
          - reactor / vessel（带夹套或盘管）：工艺端口 c1（process）+ 夹套/盘管 c2（utility）

        B 类 — 全混合型（单 channel）：
          - mixer：所有 process 端口同 channel "c1"

        C 类 — 全分流型（单 channel）：
          - separator / 闪蒸罐 / 过滤器：所有 process 端口同 channel "c1"

        D 类 — 单通道型：
          - pump / compressor / tank / 单进单出 vessel：channel = "c1" 或留空

        E 类 — 特殊结构：
          - distillation_column：channel 留空，依赖 orientation 描述层位
          - 多段反应器：每段独立 channel；段间封闭时单 channel；模糊时留空

        硬约束：
          - 同一 channel 至少应含 1 个 input 和 1 个 output（否则该 channel 无意义）。
          - channel 不跨设备复用：不同设备的 "c1" 互相独立。
          - 不要为 utility 公用工程端口胡乱配对到工艺通道，宁可留空。
        """

    _OUTPUT_SPEC = """\
        【输出规范】
        每个设备节点必须包含以下字段：
        - id: 唯一标识符，格式 equip_N（如 equip_1, equip_2）
        - name: 设备中文名称（如"进料缓冲罐"），看不清时留空
        - tag: 设备位号（如"V-0101"），看不清时留空字符串""，禁止编造
        - equipment_type: 从枚举中选择
        - bbox: [x1, y1, x2, y2]，归一化坐标 0.0-1.0，必须使用小数
        - ports: 端口数组，每个端口含 id/direction/category/orientation/label/position/channel

        坐标规则：
        - 范围 [0.0, 1.0]，x 从左到右，y 从上到下
        - 必须使用小数（如 0.205），禁止使用分数（如 1/5）
        """

    _MANDATORY_CHECK = """\
        【强制自检 — 输出前逐项执行】
        □ 检查1: equipment 列表中是否有 boundary_node（含"至/来自/界区/系统"字样）？有则删除。
        □ 检查2: 是否有纯文字标注（无位号、无标准符号）？有则删除。
        □ 检查3: 是否有阀门/仪表/管线被误识别为设备？有则删除。
        □ 检查4: 每个端口是否对应真实可见的外部连接管线？若不是，删除该端口。
        □ 检查5: 端口 position 是否在设备外轮廓附近？若在远处管线/箭头/阀门上，移到接触点。
        □ 检查6: 每个端口是否输出了 orientation 字段？取值是否为 top/bottom/left/right/unknown？
        □ 检查7: 对每个 direction="input" 的端口，确认管线上有箭头朝向设备；无证据则改为"unknown"。
        □ 检查8: 对每个 direction="output" 的端口，确认管线上有箭头背离设备；无证据则改为"unknown"。
        □ 检查9: 坐标是否均为小数格式？范围是否在 [0.0, 1.0]？
        □ 检查10: 多端口（input+output 总数 ≥ 2）设备必须输出 channel；每个 channel 至少含 1 个 input 与 1 个 output；不混合的设备（换热器等）必须输出至少 2 个 channel。
        """

    _OUTPUT_FORMAT = """\
        【输出要求】
        直接输出纯 JSON，不要输出 markdown，不要输出解释文字，不要输出 schema 之外的字段。

        {{
          "equipment": [
            {{
              "id": "equip_1",
              "name": "进料预热器",
              "tag": "E-0102",
              "equipment_type": "heat_exchanger",
              "bbox": [0.45, 0.40, 0.55, 0.50],
              "ports": [
                {{
                  "id": "equip_1_in_1",
                  "direction": "input",
                  "category": "process",
                  "orientation": "top",
                  "label": "",
                  "position": [0.50, 0.40],
                  "channel": "c1"
                }},
                {{
                  "id": "equip_1_out_1",
                  "direction": "output",
                  "category": "process",
                  "orientation": "bottom",
                  "label": "",
                  "position": [0.50, 0.50],
                  "channel": "c1"
                }},
                {{
                  "id": "equip_1_in_2",
                  "direction": "input",
                  "category": "process",
                  "orientation": "right",
                  "label": "",
                  "position": [0.55, 0.45],
                  "channel": "c2"
                }},
                {{
                  "id": "equip_1_out_2",
                  "direction": "output",
                  "category": "process",
                  "orientation": "left",
                  "label": "",
                  "position": [0.45, 0.45],
                  "channel": "c2"
                }}
              ]
            }},
            {{
              "id": "equip_2",
              "name": "脱丙烷塔",
              "tag": "T-201",
              "equipment_type": "distillation_column",
              "bbox": [0.47, 0.2, 0.53, 0.8],
              "ports": [
                {{
                  "id": "equip_2_out_1",
                  "direction": "output",
                  "category": "process",
                  "orientation": "top",
                  "label": "",
                  "position": [0.5, 0.21],
                  "channel": ""
                }},
                {{
                  "id": "equip_2_in_1",
                  "direction": "input",
                  "category": "process",
                  "orientation": "left",
                  "label": "",
                  "position": [0.47, 0.5],
                  "channel": ""
                }},
                {{
                  "id": "equip_2_out_2",
                  "direction": "output",
                  "category": "process",
                  "orientation": "bottom",
                  "label": "",
                  "position": [0.5, 0.79],
                  "channel": ""
                }}
              ]
            }}
          ]
        }}"""

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]

        if context.has_image_size:
            sections.append(self.build_image_size_section(context.image_size))

        if context.has_process_description:
            sections.append(self.build_process_description_section(context.process_description))

        sections.extend(
            [
                self._RECOGNITION_FLOW,
                self._EXCLUSIONS,
                self._TAG_AND_TYPE,
                self._BBOX_RULES,
                self._PORT_RECOGNITION,
                self._PORT_DIRECTION,
                self._PORT_ORIENTATION,
                self._PORT_CHANNEL,
                self._OUTPUT_SPEC,
                self._MANDATORY_CHECK,
                self._OUTPUT_FORMAT,
            ]
        )

        result = "\n".join(s for s in sections if s)

        return result

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["equipment"],
            "properties": {
                "equipment": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "id",
                            "name",
                            "tag",
                            "equipment_type",
                            "bbox",
                            "ports",
                        ],
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "tag": {"type": "string"},
                            "equipment_type": {
                                "type": "string",
                                "enum": _EQUIPMENT_TYPE_VALUES,
                            },
                            "bbox": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 4,
                                "maxItems": 4,
                            },
                            "ports": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": [
                                        "id",
                                        "direction",
                                        "category",
                                        "orientation",
                                        "label",
                                        "position",
                                        "channel",
                                    ],
                                    "properties": {
                                        "id": {"type": "string"},
                                        "direction": {
                                            "type": "string",
                                            "enum": ["input", "output", "unknown"],
                                        },
                                        "category": {
                                            "type": "string",
                                            "enum": ["process", "utility"],
                                        },
                                        "orientation": {
                                            "type": "string",
                                            "enum": ["top", "bottom", "left", "right", "unknown"],
                                        },
                                        "label": {"type": "string"},
                                        "position": {
                                            "type": "array",
                                            "items": {"type": "number"},
                                            "minItems": 2,
                                            "maxItems": 2,
                                        },
                                        "channel": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }


@register_prompt("equipment", "v2")
class EquipmentPromptBuilderV2(PromptBuilder):
    expert_type = "equipment"
    version = "v2"
    description = "角色+目标"


    _ROLE = """\
        【角色】
        你是PFD设备识别专家。你的任务：从图中提取有标准位号+有可见符号主体的设备节点，并为每个设备识别其连接端口（含方向）。

        范围边界：
        - 你能识别：带标准位号（P-/E-/V-/T-/R-/C-XXX）的泵、换热器、容器、塔器、反应器、混合器、分离器等标准设备符号
        - 你不能识别：阀门、仪表、管线、文字标注、边界节点（"至XXX"/"来自XXX"/"界区"/"系统"）
        """

    _TAG_AND_TYPE = f"""\
        【设备位号与类型】
        位号格式：前缀-数字编号[后缀]，如 P-0101、E-0201A、V-0305B
        标准前缀：P（泵）、E（换热器）、V（容器/储罐）、T（塔器）、R（反应器）、C（压缩机）、S（分离器）、F（过滤器）、H（加热炉）、M（混合器）

        equipment_type 只能使用以下枚举值：
        - {_EQUIPMENT_TYPE_TEXT_INLINE}
        """

    _BBOX_RULES = """\
        【bbox 标注规则】
        bbox = [x1, y1, x2, y2]，只框设备可见图形主体。

        必须包含：设备符号的可见轮廓和内部结构
        必须排除：位号文字、中文名称、下划线、功率/热负荷文字、介质文字、仪表、阀门、箭头、管线、虚线控制框

        特殊情形：
        - 设备主体被管线穿过 → bbox 仍以设备外轮廓为准，管线延伸到设备外的部分不属于 bbox
        - 符号很窄（如混合器）→ bbox 也应很窄，不要为了包含文字而放大
        """

    # 端口识别规则复用 V1，确保输出 schema 与 V1 一致
    _PORT_RECOGNITION = EquipmentPromptBuilderV1._PORT_RECOGNITION
    _PORT_DIRECTION = EquipmentPromptBuilderV1._PORT_DIRECTION
    _PORT_ORIENTATION = EquipmentPromptBuilderV1._PORT_ORIENTATION
    _PORT_CHANNEL = EquipmentPromptBuilderV1._PORT_CHANNEL
    _MANDATORY_CHECK = EquipmentPromptBuilderV1._MANDATORY_CHECK

    _OUTPUT_SPEC = """\
        【输出规范】
        每个设备节点必须包含以下字段：
        - id: 唯一标识符，格式 equip_N（如 equip_1, equip_2）
        - name: 设备中文名称（如"进料缓冲罐"），看不清时留空
        - tag: 设备位号（如"V-101"），看不清时留空字符串""，禁止编造
        - equipment_type: 从枚举中选择
        - bbox: [x1, y1, x2, y2]，归一化坐标 0.0-1.0，必须使用小数
        - ports: 端口数组，每个端口含 id/direction/category/orientation/label/position/channel

        坐标规则：
        - 范围 [0.0, 1.0]，x 从左到右，y 从上到下
        - 必须使用小数（如 0.205），禁止使用分数（如 1/5）
        """

    _OUTPUT_FORMAT = """\
        【输出要求】
        直接输出纯 JSON，不要输出 markdown，不要输出解释文字，不要输出 schema 之外的字段。

        {{
          "equipment": [
            {{
              "id": "equip_1",
              "name": "进料缓冲罐",
              "tag": "V-XXX16",
              "equipment_type": "vessel",
              "position": [0.205, 0.415],
              "bbox": [0.19, 0.39, 0.22, 0.44]
            }}
          ]
        }}"""

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]

        if context.has_image_size:
            sections.append(self.build_image_size_section(context.image_size))

        if context.has_process_description:
            sections.append(self.build_process_description_section(context.process_description))

        sections.extend(
            [
                self._TAG_AND_TYPE,
                self._BBOX_RULES,
                self._PORT_RECOGNITION,
                self._PORT_DIRECTION,
                self._PORT_ORIENTATION,
                self._PORT_CHANNEL,
                self._OUTPUT_SPEC,
                self._MANDATORY_CHECK,
                self._OUTPUT_FORMAT,
            ]
        )

        result = "\n".join(s for s in sections if s)

        return result

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["equipment"],
            "properties": {
                "equipment": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "id",
                            "name",
                            "tag",
                            "equipment_type",
                            "bbox",
                            "ports",
                        ],
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "tag": {"type": "string"},
                            "equipment_type": {
                                "type": "string",
                                "enum": _EQUIPMENT_TYPE_VALUES,
                            },
                            "bbox": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 4,
                                "maxItems": 4,
                            },
                            "ports": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": [
                                        "id",
                                        "direction",
                                        "category",
                                        "orientation",
                                        "label",
                                        "position",
                                        "channel",
                                    ],
                                    "properties": {
                                        "id": {"type": "string"},
                                        "direction": {
                                            "type": "string",
                                            "enum": ["input", "output", "unknown"],
                                        },
                                        "category": {
                                            "type": "string",
                                            "enum": ["process", "utility"],
                                        },
                                        "orientation": {
                                            "type": "string",
                                            "enum": ["top", "bottom", "left", "right", "unknown"],
                                        },
                                        "label": {"type": "string"},
                                        "position": {
                                            "type": "array",
                                            "items": {"type": "number"},
                                            "minItems": 2,
                                            "maxItems": 2,
                                        },
                                        "channel": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
