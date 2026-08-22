from typing import Any

from src.core.models import BoundaryType

from src.agent.prompts.core.base import PromptBuilder
from src.agent.prompts.core.context import PromptContext
from src.agent.prompts.core.registry import register_prompt

# 从 BoundaryType 枚举动态获取边界类型值，避免硬编码
_BOUNDARY_TYPE_VALUES: list[str] = [e.value for e in BoundaryType]


@register_prompt("boundary_node", "v1")
class BoundaryNodePromptBuilderV1(PromptBuilder):
    expert_type = "boundary_node"
    version = "v1"
    description = "详细"

    _ROLE = """
        你是一个专业的 PFD 边界节点识别专家。你的任务是识别工艺流程图中的界区节点和跨图纸连接节点。
        """

    _GOALS = """\
        【目标】
        识别以下4类节点，详细定义见【类型判别规则】。
        """

    _TYPE_DISTINCTION = """\
        【类型判别规则 - 必须优先执行】

        1. boundary_in / boundary_out 界区节点特征：
           - 主要视觉特征：矩形箭头
           - 通常存在介质名称（如中压蒸汽、热油、燃料气等）
           - boundary_in（界区进料）：矩形箭头指向管线方向，即箭头从图纸边缘指向主图内部管线
           - boundary_out（界区出料）：矩形箭头指向图纸边缘方向，即箭头从主图管线指向图纸边缘、远离主图区域
           - 不得用左右位置或介质类型替代箭头方向判断：右侧的中压蒸汽、热油、燃料气等既可能是 boundary_in，也可能是 boundary_out

        2. cross_drawing_in / cross_drawing_out 跨图纸节点特征：
           - 主要视觉特征：矩形箭头
           - 一般来说，跨图纸节点有"自/至 XXX图纸 XXX设备位号"文字描述（如"自PFD-0104 P-81002"）
           - cross_drawing_in（跨图纸来）：矩形箭头指向主流程中的管线，表示物料从另一张图纸流入
           - cross_drawing_out（跨图纸去）：矩形箭头指向图纸边缘、远离主图管线，表示物料流向另一张图纸
           - 强跨图纸证据：PFD-XXXX / DWG / 图号，或明确设备位号引用（如自P-101、至V-202），或"另一张图纸/续页/see drawing"说明

        3. boundary_in / boundary_out与cross_drawing_in / cross_drawing_out 的区别就在于是否存在至/自设备位号V-0101，T0101等描述文字，存在就是跨图纸节点，不存在就是界区节点
        """

    _CRITICAL_SWEEP = """\
        【最高优先级执行清单】
        输出前必须按"先召回、再过滤"执行：

        1. 高召回候选 sweep：
           - 扫描图纸左右两侧及边缘区域的跨图纸/边界连接符号
           - 找出所有连接到管线端点的 PFD-XXXX、跨图纸箭头框、边界箭头框、界区连接符号、同一行来源/去向说明
           - 多条平行边界线、多行相邻跨图纸标签、重复编号或重复介质名，都必须逐行拆开，不得合并成一个大框

        2. 分类型证据过滤：
           - 对每个候选节点按 boundary_in / boundary_out 或 cross_drawing_in / cross_drawing_out 分别套用最小证据门槛
           - 不要因为不确定直接忽略明显候选；先列候选，再删除证据不足者
        """

    _PRINCIPLES = """
        【总原则】
        1. 只输出有明确语义证据的边界/跨图纸节点
        2. 节点 id 必须使用简短唯一标识符，如 bnd_1
        3. 所有 bbox 必须使用 0.0-1.0 归一化坐标
        4. 只输出解析真正使用的字段，不要补充无关字段
        5. 每个端口必须输出唯一 id，建议格式为 {节点id}_in_1 或 {节点id}_out_1
        6. 端口 position 需要你自己根据 bbox 和管线连接方向计算输出
        """

    _BOUNDARY_RULES = """
        【边界/跨图纸节点识别与框选】
        节点定义："跨图/边界连接符号 + 同一行紧邻说明文字 + 管线端点"的整体。bbox 必须包含这三部分，但禁止包含相邻行文字、大片空白或远离节点的长管线。

        1. bbox 框选规则：
           - 应覆盖：边界箭头/跨图符号、PFD/DWG/图号文字、管线端点、紧邻同一行说明
           - 必须紧凑，优先略微欠框，不过度外扩
           - 禁止包含：相邻行文字、大片空白、远离节点的长说明或长直管线
        2. 拆分/合并规则：
           - 同一管线端点的同一组文字 → 一个节点，不拆
           - 多条平行管线、多行标签、不同管线端点 → 必须拆分为多个节点
           - 如果 bbox 覆盖了多条平行边界线或多行标签，必须拆分
        3. 识别前提：
           - 只有当管线在图纸边缘结束，或明显连接到跨图纸标签/去向说明时，才识别为 boundary / cross_drawing
           - 普通流股编号、设备位号、介质标注、内部延伸管线 → 不识别为 boundary / cross_drawing
        4. 端口位置不通过视觉获取，通过语义判断+计算规则得到（根据 bbox 和管线连接方向确定）：
           - 参与当前图纸管线连接的端口：放在 bbox与管线连接的那条边的中心点[~, (y1+y2)/2]
           - cross_drawing 的非参与端口（指向图纸边缘）：放在 bbox 对侧边的中心点[~, (y1+y2)/2]
           - 举例：若一个 boundary_in 节点的 bbox 左侧连接管线、右侧靠近图纸边缘，则输出端口在 bbox 左侧边中心[x1, (y1+y2)/2]
        """

    _NEGATIVE_EXAMPLES = """
        【负例：以下不要输出为 boundary 节点】
        - 普通设备 nozzle 箭头
        - 普通流向箭头
        - OCR 残缺文字或半个标签
        - 孤立介质标签或公用工程缩写
        - 仅有管线编号且管线继续延伸的内部流股
        """

    _BOUNDARY_FIELDS = """
        【边界节点字段】
        每个节点都有：
        - boundary_type：区分界区进料/界区出料/跨图纸来/跨图纸去（必填）
        - bbox：边界框坐标，[x1, y1, x2, y2] 归一化坐标（必填）
        - ports：端口列表，包含 id 和方向(direction)
        - equipment_tag（关联设备位号列表，例如"P-81004A/B",要写成["P-81004A"，"P-81004B"]）
        - drawing_id（图纸编号,例如"PFD-0101"）
        - description（来源/去向/物料描述，例如"八碳烯转化原料 自P-81004A/B"）
        """

    _SELF_CHECK = """
        【自检】
        1. 是否把文字说明误识别成 boundary 节点本体之外的多个节点
        2. bbox 是否覆盖多条平行线、多行标签或大片空白 → 必须拆分或收紧
        3. 每个节点是否满足最小证据（PFD/去向词/图纸边缘终点至少其一）
        4. 是否把孤立介质名、设备喷嘴箭头、普通流向箭头误识别为 boundary / cross_drawing
        """

    _OUTPUT_FORMAT = """
        【输出要求】
        直接输出纯 JSON，不要输出 markdown，不要输出解释文字。
        为避免节点多时 JSON 过长，输出必须紧凑：
        1. 必填字段：boundary_type、equipment_tag(无则填[])、drawing_id(无则填"")、description(无则填"")——不得省略
        2. ports 内输出 id、direction、category、position；label 为空时不输出
        3. boundary_in/boundary_out恰好1个port；cross_drawing_in/cross_drawing_out恰好2个port（1个input + 1个output）
        4. 所有坐标使用小数（如0.5），禁止分数（如1/2）

        {{
          "boundary_node": [
            {{
              "id": "bnd_1",
              "boundary_type": "boundary_in",
              "bbox": [0.02, 0.30, 0.08, 0.34],
              "equipment_tag": [],
              "drawing_id": "",
              "description": "原料油",
              "ports": [
                {{
                  "id": "bnd_1_out_1",
                  "direction": "output",
                  "category": "process",
                  "position": [0.08, 0.32]
                }}
              ]
            }},
            {{
              "id": "cross_2",
              "boundary_type": "cross_drawing_in",
              "bbox": [0.92, 0.43, 0.98, 0.47],
              "equipment_tag": ["P-81002"],
              "drawing_id": "PFD-0104",
              "description": "原料自P-81002",
              "ports": [
                {{
                  "id": "cross_2_in_1",
                  "direction": "input",
                  "category": "process",
                  "position": [0.98, 0.45]
                }},
                {{
                  "id": "cross_2_out_1",
                  "direction": "output",
                  "category": "process",
                  "position": [0.92, 0.45]
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
                self._GOALS,
                self._TYPE_DISTINCTION,
                self._CRITICAL_SWEEP,
                self._PRINCIPLES,
                self._BOUNDARY_RULES,
                self._NEGATIVE_EXAMPLES,
                self._BOUNDARY_FIELDS,

                self._OUTPUT_FORMAT,
            ]
        )

        result = "\n".join(s for s in sections if s)

        return result

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "boundary_node": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "id",
                            "boundary_type",
                            "bbox",
                            "equipment_tag",
                            "drawing_id",
                            "description",
                            "ports",
                        ],
                        "properties": {
                            "id": {"type": "string"},
                            "boundary_type": {
                                "type": "string",
                                "enum": _BOUNDARY_TYPE_VALUES,
                            },
                            "bbox": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 4,
                                "maxItems": 4,
                            },
                            "equipment_tag": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "drawing_id": {"type": "string"},
                            "description": {"type": "string"},
                            "ports": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 2,
                            },
                        },
                    },
                },
            },
            "required": ["boundary_node"],
        }


@register_prompt("boundary_node", "v2")
class BoundaryNodePromptBuilderV2(PromptBuilder):
    expert_type = "boundary_node"
    version = "v2"
    description = "角色+目标"

    _ROLE = """
        你是一个专业的 PFD 边界节点识别专家。你的任务是识别工艺流程图中的界区节点和跨图纸连接节点。
        """

    _GOALS = """\
        【目标】
        识别以下4类节点：
        1. boundary_in：界区进料
        2. boundary_out: 界区出料
        3. cross_drawing_in: 跨图纸进料
        4. cross_drawing_out: 跨图纸出料
        注意：boundary_in / boundary_out与cross_drawing_in / cross_drawing_out 的区别就在于是否存在至/自设备位号V-0101，T0101等描述文字，存在就是跨图纸节点，不存在就是界区节点
       """

    _BOUNDARY_FIELDS = """
        【边界节点字段】
        每个节点都有：
        - boundary_type：区分界区进料/界区出料/跨图纸进料/跨图纸出料（必填）
        - bbox：边界框坐标，[x1, y1, x2, y2]（必填）
        - ports：端口列表，包含 id 和方向(direction)
        - equipment_tag（关联设备位号列表，例如"P-81004A/B",要写成["P-81004A"，"P-81004B"]）
        - drawing_id（图纸编号,例如"PFD-0101"）
        - description（来源/去向/物料描述，例如"八碳烯转化原料 自P-81004A/B"）
        """

    _OUTPUT_FORMAT = """
        【输出要求】
        直接输出纯 JSON，不要输出 markdown，不要输出解释文字。
        为避免节点多时 JSON 过长，输出必须紧凑：
        1. 必填字段：boundary_type、equipment_tag(无则填[])、drawing_id(无则填"")、description(无则填"")——不得省略
        2. ports 内输出 id、direction、category、position；label 为空时不输出
        3. boundary_in/boundary_out恰好1个port；cross_drawing_in/cross_drawing_out恰好2个port（1个input + 1个output）
        4. 所有坐标使用小数（如0.5），禁止分数（如1/2）

        {{
          "boundary_node": [
            {{
              "id": "bnd_1",
              "boundary_type": "boundary_in",
              "bbox": [0.02, 0.30, 0.08, 0.34],
              "equipment_tag": [],
              "drawing_id": "",
              "description": "原料油",
              "ports": [
                {{
                  "id": "bnd_1_out_1",
                  "direction": "output",
                  "category": "process",
                  "position": [0.08, 0.32]
                }}
              ]
            }},
            {{
              "id": "cross_2",
              "boundary_type": "cross_drawing_in",
              "bbox": [0.92, 0.43, 0.98, 0.47],
              "equipment_tag": ["P-81002"],
              "drawing_id": "PFD-0104",
              "description": "原料自P-81002",
              "ports": [
                {{
                  "id": "cross_2_in_1",
                  "direction": "input",
                  "category": "process",
                  "position": [0.98, 0.45]
                }},
                {{
                  "id": "cross_2_out_1",
                  "direction": "output",
                  "category": "process",
                  "position": [0.92, 0.45]
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
                self._GOALS,
                self._BOUNDARY_FIELDS,
                self._OUTPUT_FORMAT,
            ]
        )

        result = "\n".join(s for s in sections if s)

        return result

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "boundary_node": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "id",
                            "boundary_type",
                            "bbox",
                            "equipment_tag",
                            "drawing_id",
                            "description",
                            "ports",
                        ],
                        "properties": {
                            "id": {"type": "string"},
                            "boundary_type": {
                                "type": "string",
                                "enum": _BOUNDARY_TYPE_VALUES,
                            },
                            "bbox": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 4,
                                "maxItems": 4,
                            },
                            "equipment_tag": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "drawing_id": {"type": "string"},
                            "description": {"type": "string"},
                            "ports": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 2,
                            },
                        },
                    },
                },
            },
            "required": ["boundary_node"],
        }


@register_prompt("boundary_node", "v3")
class BoundaryNodePromptBuilderV3(PromptBuilder):
    expert_type = "boundary_node"
    version = "v3"
    description = "界区节点与跨图纸节点条件变更"

    _ROLE = """
        你是一个专业的 PFD 边界节点识别专家。你的任务是识别工艺流程图中的界区节点和跨图纸连接节点。
        """

    _GOALS = """\
        【目标】
        识别以下4类节点，详细定义见【类型判别规则】。
        """

    _TYPE_DISTINCTION = """\
        【类型判别规则 - 必须优先执行】

        1. boundary_in / boundary_out 界区节点特征：
           - 主要视觉特征：矩形箭头
           - 通常存在介质名称（如中压蒸汽、热油、燃料气等）
           - boundary_in（界区进料）：矩形箭头指向管线方向，即箭头从图纸边缘指向主图内部管线
           - boundary_out（界区出料）：矩形箭头指向图纸边缘方向，即箭头从主图管线指向图纸边缘、远离主图区域
           - 不得用左右位置或介质类型替代箭头方向判断：右侧的中压蒸汽、热油、燃料气等既可能是 boundary_in，也可能是 boundary_out

        2. cross_drawing_in / cross_drawing_out 跨图纸节点特征：
           - 主要视觉特征：矩形箭头
           - 一般来说，跨图纸节点有"自/至 XXX图纸 XXX设备位号"文字描述（如"自PFD-0104 P-81002"）
           - cross_drawing_in（跨图纸来）：矩形箭头指向主流程中的管线，表示物料从另一张图纸流入
           - cross_drawing_out（跨图纸去）：矩形箭头指向图纸边缘、远离主图管线，表示物料流向另一张图纸
           - 强跨图纸证据：PFD-XXXX / DWG / 图号，或明确设备位号引用（如自P-101、至V-202），或"另一张图纸/续页/see drawing"说明
           - 设备位号引用只有在同时出现图纸编号、续页、跨图纸符号或明确跨图纸说明时，才能辅助判为 cross_drawing；设备位号不能单独作为跨图纸证据

        3. boundary_in / boundary_out与cross_drawing_in / cross_drawing_out 的区别就在于是否存在至/自设备位号V-0101，T0101等描述文字，存在就是跨图纸节点，不存在就是界区节点
        """

    _CRITICAL_SWEEP = """\
        【最高优先级执行清单】
        输出前必须按"先召回、再过滤"执行：

        1. 高召回候选 sweep：
           - 扫描图纸左右两侧及边缘区域的跨图纸/边界连接符号
           - 找出所有连接到管线端点的 PFD-XXXX、跨图纸箭头框、边界箭头框、界区连接符号、同一行来源/去向说明
           - 多条平行边界线、多行相邻跨图纸标签、重复编号或重复介质名，都必须逐行拆开，不得合并成一个大框

        2. 分类型证据过滤：
           - 对每个候选节点按 boundary_in / boundary_out 或 cross_drawing_in / cross_drawing_out 分别套用最小证据门槛
           - 不要因为不确定直接忽略明显候选；先列候选，再删除证据不足者
        """

    _PRINCIPLES = """
        【总原则】
        1. 只输出有明确语义证据的边界/跨图纸节点
        2. 节点 id 必须使用简短唯一标识符，如 bnd_1
        3. 所有 bbox 必须使用 0.0-1.0 归一化坐标
        4. 只输出解析真正使用的字段，不要补充无关字段
        5. 每个端口必须输出唯一 id，建议格式为 {节点id}_in_1 或 {节点id}_out_1
        6. 端口 position 需要你自己根据 bbox 和管线连接方向计算输出
        """

    _BOUNDARY_RULES = """
        【边界/跨图纸节点识别与框选】
        节点定义："跨图/边界连接符号 + 同一行紧邻说明文字 + 管线端点"的整体。bbox 必须包含这三部分，但禁止包含相邻行文字、大片空白或远离节点的长管线。

        1. bbox 框选规则：
           - 应覆盖：边界箭头/跨图符号、PFD/DWG/图号文字、管线端点、紧邻同一行说明
           - 必须紧凑，优先略微欠框，不过度外扩
           - 禁止包含：相邻行文字、大片空白、远离节点的长说明或长直管线
        2. 拆分/合并规则：
           - 同一管线端点的同一组文字 → 一个节点，不拆
           - 多条平行管线、多行标签、不同管线端点 → 必须拆分为多个节点
           - 如果 bbox 覆盖了多条平行边界线或多行标签，必须拆分
        3. 识别前提：
           - 只有当管线在图纸边缘结束，或明显连接到跨图纸标签/去向说明时，才识别为 boundary / cross_drawing
           - 普通流股编号、设备位号、介质标注、内部延伸管线 → 不识别为 boundary / cross_drawing
        4. 端口位置不通过视觉获取，通过语义判断+计算规则得到（根据 bbox 和管线连接方向确定）：
           - 参与当前图纸管线连接的端口：放在 bbox与管线连接的那条边的中心点[~, (y1+y2)/2]
           - cross_drawing 的非参与端口（指向图纸边缘）：放在 bbox 对侧边的中心点[~, (y1+y2)/2]
           - 举例：若一个 boundary_in 节点的 bbox 左侧连接管线、右侧靠近图纸边缘，则输出端口在 bbox 左侧边中心[x1, (y1+y2)/2]
        """

    _NEGATIVE_EXAMPLES = """
        【负例：以下不要输出为 boundary 节点】
        - 普通设备 nozzle 箭头
        - 普通流向箭头
        - OCR 残缺文字或半个标签
        - 孤立介质标签或公用工程缩写
        - 仅有管线编号且管线继续延伸的内部流股
        """

    _BOUNDARY_FIELDS = """
        【边界节点字段】
        每个节点都有：
        - boundary_type：区分界区进料/界区出料/跨图纸来/跨图纸去（必填）
        - bbox：边界框坐标，[x1, y1, x2, y2] 归一化坐标（必填）
        - ports：端口列表，包含 id 和方向(direction)
        - equipment_tag（关联设备位号列表，例如"P-81004A/B",要写成["P-81004A"，"P-81004B"]）
        - drawing_id（图纸编号,例如"PFD-0101"）
        - description（来源/去向/物料描述，例如"八碳烯转化原料 自P-81004A/B"）
        """

    _SELF_CHECK = """
        【自检】
        1. 是否把文字说明误识别成 boundary 节点本体之外的多个节点
        2. bbox 是否覆盖多条平行线、多行标签或大片空白 → 必须拆分或收紧
        3. 每个节点是否满足最小证据（PFD/去向词/图纸边缘终点至少其一）
        4. 是否把孤立介质名、设备喷嘴箭头、普通流向箭头误识别为 boundary / cross_drawing
        """

    _OUTPUT_FORMAT = """
        【输出要求】
        直接输出纯 JSON，不要输出 markdown，不要输出解释文字。
        为避免节点多时 JSON 过长，输出必须紧凑：
        1. 必填字段：boundary_type、equipment_tag(无则填[])、drawing_id(无则填"")、description(无则填"")——不得省略
        2. ports 内输出 id、direction、category、position；label 为空时不输出
        3. boundary_in/boundary_out恰好1个port；cross_drawing_in/cross_drawing_out恰好2个port（1个input + 1个output）
        4. 所有坐标使用小数（如0.5），禁止分数（如1/2）

        {{
          "boundary_node": [
            {{
              "id": "bnd_1",
              "boundary_type": "boundary_in",
              "bbox": [0.02, 0.30, 0.08, 0.34],
              "equipment_tag": [],
              "drawing_id": "",
              "description": "原料油",
              "ports": [
                {{
                  "id": "bnd_1_out_1",
                  "direction": "output",
                  "category": "process",
                  "position": [0.08, 0.32]
                }}
              ]
            }},
            {{
              "id": "cross_2",
              "boundary_type": "cross_drawing_in",
              "bbox": [0.92, 0.43, 0.98, 0.47],
              "equipment_tag": ["P-81002"],
              "drawing_id": "PFD-0104",
              "description": "原料自P-81002",
              "ports": [
                {{
                  "id": "cross_2_in_1",
                  "direction": "input",
                  "category": "process",
                  "position": [0.98, 0.45]
                }},
                {{
                  "id": "cross_2_out_1",
                  "direction": "output",
                  "category": "process",
                  "position": [0.92, 0.45]
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
                self._GOALS,
                self._TYPE_DISTINCTION,
                self._CRITICAL_SWEEP,
                self._PRINCIPLES,
                self._BOUNDARY_RULES,
                self._NEGATIVE_EXAMPLES,
                self._BOUNDARY_FIELDS,

                self._OUTPUT_FORMAT,
            ]
        )

        result = "\n".join(s for s in sections if s)

        return result

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "boundary_node": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "id",
                            "boundary_type",
                            "bbox",
                            "equipment_tag",
                            "drawing_id",
                            "description",
                            "ports",
                        ],
                        "properties": {
                            "id": {"type": "string"},
                            "boundary_type": {
                                "type": "string",
                                "enum": _BOUNDARY_TYPE_VALUES,
                            },
                            "bbox": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 4,
                                "maxItems": 4,
                            },
                            "equipment_tag": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "drawing_id": {"type": "string"},
                            "description": {"type": "string"},
                            "ports": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 2,
                            },
                        },
                    },
                },
            },
            "required": ["boundary_node"],
        }
