from typing import Any

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt


@register_prompt("reactor_assembly", "v1")
class ReactorAssemblyPromptBuilderV1(PromptBuilder):
    expert_type = "reactor_assembly"
    version = "v1"
    description = "V1 反应器装配图设计数据提取：按参考输出格式提取反应器两侧介质、密度、温度和流向"

    _ROLE = """
        你是一个专业的化工反应器装配图信息提取专家。你的任务是从反应器装配图、标题栏、管口表、设计基本数据表、装配明细表和局部剖视图中提取反应器设计数据。
        """

    _RULES = """
        【总体原则】
        1. 只提取图中可见文字、表格和标注信息，不要凭空编造。
        2. 优先读取右侧/右下侧的"设计基本数据""管口明细表""图纸标题栏"；必要时结合主视图管口标注确认壳程/管程。
        3. 输出字段必须严格遵循参考数据模型；找不到的字符串填空字符串，找不到的数值填 null。
        4. 单位必须保留原图单位；摄氏度统一写作"℃"，密度可按图中写法保留 kg/m3 或 kg/m³。
        5. id 不是图纸提取字段，而是外部案例/样本编号；如果上下文给出 source_image_id/reactor_id，必须原样填写该编号；如果上下文未给出，留空字符串，不要从图纸位号推导。
        6. tag 优先读取设备位号/图题中的 R-XXXX、RXXXX、R-XXXXA/B 等；保留原图可见形式。
        7. name 优先读取图纸名称或设计数据表中的设备名称，如"示例反应器"。

        【字段说明】
        - id：外部案例/样本编号，字符串，不是图纸中的设备位号。
        - tag：设备位号，字符串。
        - name：设备名称，字符串。
        - flow_pattern：两侧物流相对流向，由 shell_side.flow_direction 与 tube_side.flow_direction 的相对方向决定：
          * countercurrent：逆流——壳程与管程物料流向相反（如壳程从上往下、管程从下往上）
          * cocurrent：并流——壳程与管程物料流向相同（如壳程和管程都从上往下）
          * crossflow：错流——壳程与管程物料流向互相垂直（如壳程水平、管程垂直）
          * unknown：图中无法判断流向
          flow_pattern 为对象，包含 value（流向类型枚举）、evidence（判断依据）、confidence（置信度）。
        - shell_side：壳程数据。
        - tube_side：管程数据。
        - shell_side/tube_side.type：图中对应侧的中文类型或物料描述。
        - shell_side/tube_side.medium：介质名称列表，数组格式。每种介质为单独的字符串元素。若同一侧有多个介质，每个介质单独作为数组元素，如["介质A", "介质B"]或["介质A", "介质B", "介质C"]。不要用斜杠或逗号合并为一个字符串。
        - shell_side/tube_side.flow_direction：该侧物料的整体流向，为对象，包含 value（流向枚举）、evidence（判断依据）、confidence（置信度）。
          value 取值范围：
          * up：物料整体从下往上流
          * down：物料整体从上往下流
          * left：物料整体从右往左流
          * right：物料整体从左往右流
          * unknown：无法判断
          判断方法：查看图纸右侧的反应器结构图（局部剖视图/管口方位图），根据该侧物料进口和出口的空间位置确定流向。进口在下、出口在上则为 up；进口在上、出口在下则为 down；进口在左、出口在右则为 right；进口在右、出口在左则为 left。
        - density：密度。支持单介质和多介质两种形式：
          * 单介质：{"default": {"value": 数值或null, "unit": "单位"}}
          * 多介质（气液两相或多种介质）：{"气": {"value": 10.0, "unit": "kg/m3"}, "液": {"value": 800.0, "unit": "kg/m3"}} 或 {"介质A": {"value": 990.0, "unit": "kg/m3"}, "介质B": {"value": 998.0, "unit": "kg/m3"}}
          键名为介质相态或介质名称，值为 quantity 对象。
        - working_temperature：工作温度，包含进口和出口温度。支持单介质和多介质两种形式：
          * 单介质：{"default": {"inlet": {"value": 数值或null, "unit": "℃"}, "outlet": {"value": 数值或null, "unit": "℃"}}}
          * 多介质（如壳程进口 30/10）：{"介质A": {"inlet": {"value": 30, "unit": "℃"}, "outlet": {"value": 40, "unit": "℃"}}, "介质B": {"inlet": {"value": 10, "unit": "℃"}, "outlet": {"value": 20, "unit": "℃"}}}
          键名为介质名称或"default"，值为包含 inlet（进口温度）和 outlet（出口温度）的对象，每个都是 quantity 格式。
        - shell_side/tube_side.evidence：该侧数据提取的最短可复核证据，如"设计数据表壳程行"或"管口表a/b行"。
        - shell_side/tube_side.confidence：该侧数据提取的置信度，0.0-1.0。

        【设计压力与设计温度】
        1. design_pressure（设计压力）：从设计基本数据表或标题栏中读取，通常标注为"设计压力"或"Design Pressure"。
        2. design_temperature（设计温度）：从设计基本数据表或标题栏中读取，通常标注为"设计温度"或"Design Temperature"。
        3. design_pressure 和 design_temperature 均为 Quantity 格式（value/unit/raw_text），仅存单一值。
        4. 若设计基本数据表中壳程和管程分别标注了设计压力/设计温度，取壳程值填入；若仅有一个统一值，直接填入。
        5. raw_text 保留图纸原始标注全文，如"0.6 MPaG"。
        6. 工作温度（进口/出口温度）已归入 shell_side.working_temperature 和 tube_side.working_temperature，不再在顶层单独提取。

        【壳程/管程判别】
        1. 表格中出现"壳程/管程"列时，以表格为准。
        2. 管口表中出现"热媒入口/热媒出口/物料进口/物料出口"等时，用管口用途辅助判断进出口温度。
        3. 不要把设计压力、工作压力、焊接温度、热处理温度误当成介质入口/出口温度。
        4. 不要把材料密度、质量、面积、厚度误当成介质密度。
        5. 如果温度或密度单元格写成斜杠组合值（例如进口 150/45、出口 140/55，或密度 10.0气/800.0液），必须拆分为字典形式，斜杠前后分别对应不同介质或相态。
          * 温度示例：进口 150/45 且介质为"蒸汽（凝结水）"或"蒸汽/凝结水"时，working_temperature = {"蒸汽": {"inlet": {"value": 150, "unit": "℃"}, "outlet": {"value": 140, "unit": "℃"}}, "凝结水": {"inlet": {"value": 45, "unit": "℃"}, "outlet": {"value": 55, "unit": "℃"}}}
          * 密度示例：10.0气/800.0液 时，density = {"气": {"value": 10.0, "unit": "kg/m3"}, "液": {"value": 800.0, "unit": "kg/m3"}}
          * 若无法判断斜杠前后对应何种介质，使用"前"/"后"作为键名，如 {"前": {"inlet": {"value": 150, "unit": "℃"}, "outlet": {"value": 140, "unit": "℃"}}, "后": {"inlet": {"value": 45, "unit": "℃"}, "outlet": {"value": 55, "unit": "℃"}}}
        6. 若只有单一介质/相态，使用 "default" 作为唯一键名。

        【管口表提取】
        1. 管口表通常位于图纸左下角，表头一般包含"符号""公称尺寸""连接法兰标准""形式/密封面""用途""接管尺寸"等列。
        2. 逐行读取管口表，每个管口对应 nozzles 数组中的一个对象。
        3. 字段映射：
          - nozzle_id：管口表"符号"列，如 a、b、c、d 等。
          - nominal_size：管口表"公称尺寸"列，如 DN100、DN150 等。
          - flange_standard：管口表"连接法兰标准"列，如 HG/T 20592、HG/T 20615 等。
          - face_type：管口表"形式/密封面"列，如 RF、FF、MFM、TG 等。
          - service_description：管口表"用途"列，保留原文，如"物料进口""冷却水出口""放空口"等。
          - pipe_size：管口表"接管尺寸"列，如 φ108×4、φ219×6 等。
        4. nozzle_role 根据用途(service_description)语义分类：
          - 物料进口、进料口、反应物入口等 → material_inlet
          - 物料出口、出料口、产物出口等 → material_outlet
          - 冷却水进口、蒸汽进口、热媒入口等公用工程进口 → utility_inlet
          - 冷却水出口、蒸汽出口、热媒出口等公用工程出口 → utility_outlet
          - 放空口、排气口 → vent
          - 排液口、排污口 → drain
          - 人孔 → manway
          - 测温口、压力表口、液位计口等仪表接口 → instrument
          - 其他无法归类的 → other
          - 不确定 → unknown
        5. elevation 为管口标高，从主视图标高线或管口表中的标高标注读取，格式为 {"value": 数值或null, "unit": "mm", "raw_text": "原图标注如EL+9350"}。若图中无标高信息，value 填 null，raw_text 填空字符串。
        6. evidence 填写最短可复核证据，如"管口表 a 行"或"管口表第2行"。
        7. confidence 为该管口信息提取的置信度，0.0-1.0。

        【物料流向判断方法】
        1. 查看图纸右侧的反应器结构图（局部剖视图/管口方位图），找到壳程和管程各自的物料进口和出口位置。
        2. 根据进口→出口的空间方向判断 flow_direction.value：
          - 进口在下方、出口在上方 → flow_direction.value = "up"
          - 进口在上方、出口在下方 → flow_direction.value = "down"
          - 进口在左侧、出口在右侧 → flow_direction.value = "right"
          - 进口在右侧、出口在左侧 → flow_direction.value = "left"
        3. 根据两侧 flow_direction.value 的相对关系推导 flow_pattern.value：
          - 壳程和管程流向相反（如一上一下）→ flow_pattern.value = "countercurrent"
          - 壳程和管程流向相同（如都往下）→ flow_pattern.value = "cocurrent"
          - 壳程和管程流向垂直（如一水平一垂直）→ flow_pattern.value = "crossflow"
        4. 如果结构图中无法看清进出口位置，flow_direction.value 填 "unknown"，flow_pattern.value 也填 "unknown"。
        5. 也可以结合管口表中 nozzle_role=material_inlet / material_outlet 的管口在结构图上的位置辅助判断 flow_direction。
        6. flow_direction 和 flow_pattern 都必须填写 evidence（判断依据）和 confidence（置信度）。
        """

    _OUTPUT_FORMAT = """
        【输出要求】
        1. 仅输出JSON，不要输出额外说明。
        2. 顶层必须直接是参考数据模型，不要包裹 markdown，不要包裹 reactor_design。
        3. 所有字段必须存在。

        {
          "id": "",
          "tag": "",
          "name": "",
          "flow_pattern": {
            "value": "countercurrent|cocurrent|crossflow|unknown",
            "evidence": "",
            "confidence": 0.0
          },
          "design_pressure": {"value": null, "unit": "MPa", "raw_text": ""},
          "design_temperature": {"value": null, "unit": "℃", "raw_text": ""},
          "shell_side": {
            "type": "",
            "medium": [],
            "flow_direction": {
              "value": "up|down|left|right|unknown",
              "evidence": "",
              "confidence": 0.0
            },
            "density": {"default": {"value": null, "unit": ""}},
            "working_temperature": {"default": {"inlet": {"value": null, "unit": ""}, "outlet": {"value": null, "unit": ""}}},
            "evidence": "",
            "confidence": 0.0
          },
          "tube_side": {
            "type": "",
            "medium": [],
            "flow_direction": {
              "value": "up|down|left|right|unknown",
              "evidence": "",
              "confidence": 0.0
            },
            "density": {"default": {"value": null, "unit": ""}},
            "working_temperature": {"default": {"inlet": {"value": null, "unit": ""}, "outlet": {"value": null, "unit": ""}}},
            "evidence": "",
            "confidence": 0.0
          },
          "nozzles": [
            {
              "nozzle_id": "",
              "service_description": "",
              "nominal_size": "",
              "flange_standard": "",
              "face_type": "",
              "pipe_size": "",
              "nozzle_role": "material_inlet|material_outlet|utility_inlet|utility_outlet|vent|drain|manway|instrument|other|unknown",
              "evidence": "",
              "confidence": 0.0
            }
          ],
          "warnings": []
        }
        """

    _CHECKLIST = """
        【自检清单】
        □ 是否只输出一个JSON对象
        □ id/tag/name 是否分别对应样本编号、设备位号、设备名称
        □ 壳程和管程是否没有混淆
        □ shell_side.flow_direction 和 tube_side.flow_direction 是否根据结构图进出口位置正确判断
        □ flow_pattern 是否与两侧 flow_direction 的相对方向一致（相反=countercurrent，相同=cocurrent，垂直=crossflow）
        □ flow_pattern 和 flow_direction 是否都填写了 evidence 和 confidence
        □ 密度字段是否来自介质密度，而不是材料密度/质量/厚度
        □ 设计压力是否从设计基本数据表或标题栏中提取
        □ 设计温度是否从设计基本数据表或标题栏中提取
        □ shell_side/tube_side 的 working_temperature 是否包含 inlet 和 outlet
        □ 温度字段是否来自介质进出口温度，而不是设计温度或焊接/热处理温度
        □ 若存在斜杠分隔的多介质/多相态值，density/working_temperature 是否为字典格式且键名正确
        □ nozzles 是否逐行提取了管口表中所有管口
        □ 每个管口的 symbol/nominal_size/flange_standard/face_type/purpose/pipe_size 是否来自管口表对应列
        □ nozzle_role 是否与 purpose 语义一致
        □ shell_side 和 tube_side 的 evidence 是否填写了最短可复核证据
        □ shell_side 和 tube_side 的 confidence 是否合理（0.0-1.0）
        □ 缺失字段是否按空字符串或 null 填充
        """

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]

        if context.has_image_size:
            sections.append(self.build_image_size_section(context.image_size))

        source_id = ""
        if context.extra:
            source_id = str(
                context.extra.get("reactor_id")
                or context.extra.get("source_image_id")
                or context.extra.get("id")
                or ""
            ).strip()
        if source_id:
            sections.append(f"【任务上下文】\n当前图像对应的反应器样本 id 为：{source_id}。")

        sections.extend([self._RULES, self._OUTPUT_FORMAT, self._CHECKLIST])
        return "\n".join(s for s in sections if s)

    def get_output_schema(self) -> dict[str, Any]:
        quantity_schema = {
            "type": "object",
            "required": ["value", "unit", "raw_text"],
            "properties": {
                "value": {"type": ["number", "null"]},
                "unit": {"type": "string"},
                "raw_text": {"type": "string"},
            },
        }
        dict_quantity_schema = {
            "type": "object",
            "additionalProperties": quantity_schema,
        }
        inlet_outlet_quantity_schema = {
            "type": "object",
            "required": ["inlet", "outlet"],
            "properties": {
                "inlet": quantity_schema,
                "outlet": quantity_schema,
            },
        }
        dict_inlet_outlet_quantity_schema = {
            "type": "object",
            "additionalProperties": inlet_outlet_quantity_schema,
        }
        classified_value_flow_direction = {
            "type": "object",
            "required": ["value", "evidence", "confidence"],
            "properties": {
                "value": {"type": "string", "enum": ["up", "down", "left", "right", "unknown"]},
                "evidence": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        }
        side_schema = {
            "type": "object",
            "required": [
                "type",
                "medium",
                "flow_direction",
                "density",
                "working_temperature",
                "evidence",
                "confidence",
            ],
            "properties": {
                "type": {"type": "string"},
                "medium": {"type": "array", "items": {"type": "string"}},
                "flow_direction": classified_value_flow_direction,
                "density": dict_quantity_schema,
                "working_temperature": dict_inlet_outlet_quantity_schema,
                "evidence": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        }
        nozzle_schema = {
            "type": "object",
            "required": [
                "nozzle_id",
                "service_description",
                "nominal_size",
                "flange_standard",
                "face_type",
                "pipe_size",
                "nozzle_role",
                "elevation",
                "evidence",
                "confidence",
            ],
            "properties": {
                "nozzle_id": {"type": "string"},
                "service_description": {"type": "string"},
                "nominal_size": {"type": "string"},
                "flange_standard": {"type": "string"},
                "face_type": {"type": "string"},
                "pipe_size": {"type": "string"},
                "nozzle_role": {
                    "type": "string",
                    "enum": [
                        "material_inlet",
                        "material_outlet",
                        "utility_inlet",
                        "utility_outlet",
                        "vent",
                        "drain",
                        "manway",
                        "instrument",
                        "other",
                        "unknown",
                    ],
                },
                "elevation": {
                    "type": "object",
                    "required": ["value", "unit", "raw_text"],
                    "properties": {
                        "value": {"type": ["number", "null"]},
                        "unit": {"type": "string"},
                        "raw_text": {"type": "string"},
                    },
                },
                "evidence": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        }
        return {
            "type": "object",
            "required": [
                "source_image_id",
                "info",
                "reactor_type",
                "flow_pattern",
                "design_pressure",
                "design_temperature",
                "shell_side",
                "tube_side",
                "nozzles",
                "warnings",
            ],
            "properties": {
                "source_image_id": {"type": "string"},
                "info": {
                    "type": "object",
                    "required": ["equipment_tag", "equipment_name", "drawing_name"],
                    "properties": {
                        "equipment_tag": {"type": "string"},
                        "equipment_name": {"type": "string"},
                        "drawing_name": {"type": "string"},
                    },
                },
                "reactor_type": {"type": "string", "enum": ["fixed_tube", "floating_head", "u_tube", "unknown"]},
                "flow_pattern": {
                    "type": "object",
                    "required": ["value", "evidence", "confidence"],
                    "properties": {
                        "value": {"type": "string", "enum": ["countercurrent", "cocurrent", "crossflow", "unknown"]},
                        "evidence": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    },
                },
                "design_pressure": quantity_schema,
                "design_temperature": quantity_schema,
                "shell_side": side_schema,
                "tube_side": side_schema,
                "nozzles": {"type": "array", "items": nozzle_schema},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
        }


@register_prompt("reactor_assembly", "v2")
class ReactorAssemblyPromptBuilderV2(PromptBuilder):
    expert_type = "reactor_assembly"
    version = "v2"
    description = "V2 反应器装配图设计数据提取（简化版）：仅角色定义+目标+输出格式，去除规则与自检清单"

    _ROLE = """
        你是一个专业的化工反应器装配图信息提取专家。你的任务是从反应器装配图、标题栏、管口表、设计基本数据表、装配明细表和局部剖视图中提取反应器设计数据。
        """

    _GOAL = """
        【提取目标】
        从反应器装配图中提取以下结构化设计数据：
        1. 设备位号 tag、设备名称 name；id 为外部样本编号（由上下文给出，不从图纸推导）。
        2. 壳程 shell_side 与管程 tube_side 两侧的：类型、介质、密度、工作温度（进口/出口）、物料流向。
        3. 流型 flow_pattern：由两侧 flow_direction 的相对方向推导（逆流 countercurrent / 并流 cocurrent / 错流 crossflow / 未知 unknown）。
        4. 设计压力 design_pressure、设计温度 design_temperature（从设计基本数据表或标题栏读取）。
        5. 管口表 nozzles：逐行提取每个管口的符号、用途、公称尺寸、法兰标准、密封面形式、接管尺寸、管口角色和标高。

        【基本要求】
        - 只提取图中可见文字、表格和标注，不凭空编造；找不到的字符串填空字符串，找不到的数值填 null。
        - 单位保留原图单位；摄氏度统一写作"℃"。
        - evidence 填写最短可复核证据，confidence 填写提取置信度（0.0-1.0）。
        """

    _OUTPUT_FORMAT = """
        【输出要求】
        1. 仅输出JSON，不要输出额外说明。
        2. 顶层必须直接是参考数据模型，不要包裹 markdown，不要包裹 reactor_design。
        3. 所有字段必须存在。

        {
          "id": "",
          "tag": "",
          "name": "",
          "flow_pattern": {
            "value": "countercurrent|cocurrent|crossflow|unknown",
            "evidence": "",
            "confidence": 0.0
          },
          "design_pressure": {"value": null, "unit": "MPa", "raw_text": ""},
          "design_temperature": {"value": null, "unit": "℃", "raw_text": ""},
          "shell_side": {
            "type": "",
            "medium": [],
            "flow_direction": {
              "value": "up|down|left|right|unknown",
              "evidence": "",
              "confidence": 0.0
            },
            "density": {"default": {"value": null, "unit": ""}},
            "working_temperature": {"default": {"inlet": {"value": null, "unit": ""}, "outlet": {"value": null, "unit": ""}}},
            "evidence": "",
            "confidence": 0.0
          },
          "tube_side": {
            "type": "",
            "medium": [],
            "flow_direction": {
              "value": "up|down|left|right|unknown",
              "evidence": "",
              "confidence": 0.0
            },
            "density": {"default": {"value": null, "unit": ""}},
            "working_temperature": {"default": {"inlet": {"value": null, "unit": ""}, "outlet": {"value": null, "unit": ""}}},
            "evidence": "",
            "confidence": 0.0
          },
          "nozzles": [
            {
              "nozzle_id": "",
              "service_description": "",
              "nominal_size": "",
              "flange_standard": "",
              "face_type": "",
              "pipe_size": "",
              "nozzle_role": "material_inlet|material_outlet|utility_inlet|utility_outlet|vent|drain|manway|instrument|other|unknown",
              "elevation": {"value": null, "unit": "mm", "raw_text": ""},
              "evidence": "",
              "confidence": 0.0
            }
          ],
          "warnings": []
        }
        """

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE, self._GOAL]

        if context.has_image_size:
            sections.append(self.build_image_size_section(context.image_size))

        source_id = ""
        if context.extra:
            source_id = str(
                context.extra.get("reactor_id")
                or context.extra.get("source_image_id")
                or context.extra.get("id")
                or ""
            ).strip()
        if source_id:
            sections.append(f"【任务上下文】\n当前图像对应的反应器样本 id 为：{source_id}。")

        sections.append(self._OUTPUT_FORMAT)
        return "\n".join(s for s in sections if s)

    def get_output_schema(self) -> dict[str, Any]:
        quantity_schema = {
            "type": "object",
            "required": ["value", "unit", "raw_text"],
            "properties": {
                "value": {"type": ["number", "null"]},
                "unit": {"type": "string"},
                "raw_text": {"type": "string"},
            },
        }
        dict_quantity_schema = {
            "type": "object",
            "additionalProperties": quantity_schema,
        }
        inlet_outlet_quantity_schema = {
            "type": "object",
            "required": ["inlet", "outlet"],
            "properties": {
                "inlet": quantity_schema,
                "outlet": quantity_schema,
            },
        }
        dict_inlet_outlet_quantity_schema = {
            "type": "object",
            "additionalProperties": inlet_outlet_quantity_schema,
        }
        classified_value_flow_direction = {
            "type": "object",
            "required": ["value", "evidence", "confidence"],
            "properties": {
                "value": {"type": "string", "enum": ["up", "down", "left", "right", "unknown"]},
                "evidence": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        }
        side_schema = {
            "type": "object",
            "required": [
                "type",
                "medium",
                "flow_direction",
                "density",
                "working_temperature",
                "evidence",
                "confidence",
            ],
            "properties": {
                "type": {"type": "string"},
                "medium": {"type": "array", "items": {"type": "string"}},
                "flow_direction": classified_value_flow_direction,
                "density": dict_quantity_schema,
                "working_temperature": dict_inlet_outlet_quantity_schema,
                "evidence": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        }
        nozzle_schema = {
            "type": "object",
            "required": [
                "nozzle_id",
                "service_description",
                "nominal_size",
                "flange_standard",
                "face_type",
                "pipe_size",
                "nozzle_role",
                "elevation",
                "evidence",
                "confidence",
            ],
            "properties": {
                "nozzle_id": {"type": "string"},
                "service_description": {"type": "string"},
                "nominal_size": {"type": "string"},
                "flange_standard": {"type": "string"},
                "face_type": {"type": "string"},
                "pipe_size": {"type": "string"},
                "nozzle_role": {
                    "type": "string",
                    "enum": [
                        "material_inlet",
                        "material_outlet",
                        "utility_inlet",
                        "utility_outlet",
                        "vent",
                        "drain",
                        "manway",
                        "instrument",
                        "other",
                        "unknown",
                    ],
                },
                "elevation": {
                    "type": "object",
                    "required": ["value", "unit", "raw_text"],
                    "properties": {
                        "value": {"type": ["number", "null"]},
                        "unit": {"type": "string"},
                        "raw_text": {"type": "string"},
                    },
                },
                "evidence": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        }
        return {
            "type": "object",
            "required": [
                "id",
                "tag",
                "name",
                "flow_pattern",
                "design_pressure",
                "design_temperature",
                "shell_side",
                "tube_side",
                "nozzles",
                "warnings",
            ],
            "properties": {
                "id": {"type": "string"},
                "tag": {"type": "string"},
                "name": {"type": "string"},
                "flow_pattern": {
                    "type": "object",
                    "required": ["value", "evidence", "confidence"],
                    "properties": {
                        "value": {"type": "string", "enum": ["countercurrent", "cocurrent", "crossflow", "unknown"]},
                        "evidence": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    },
                },
                "design_pressure": quantity_schema,
                "design_temperature": quantity_schema,
                "shell_side": side_schema,
                "tube_side": side_schema,
                "nozzles": {"type": "array", "items": nozzle_schema},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
        }
