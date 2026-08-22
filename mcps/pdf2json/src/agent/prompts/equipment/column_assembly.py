from typing import Any

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt


_COMMON_RULES = """
    【总体原则】
    1. 只提取图纸中可见文字、尺寸线、标高线、表格和符号信息，不要凭空编造。
    2. 优先读取标题栏、设计基本数据表、管口表；再结合主视图 leader line、标高和内部构件符号定位。
    3. 字符串缺失填空字符串，数值缺失填 null，数组缺失填空数组。
    4. 所有数值单位保留图中单位；DN、公称尺寸等原始文本放入 raw_text 或 nominal_size。
    5. evidence 应写最短可复核证据，如"管口表 a1-a3 进料口 + 主视图 EL+XXXXX 附近 leader line"。
    6. confidence 表示该条目的提取置信度（0.0-1.0），完全确定填1.0，部分推断填0.5-0.8，猜测填0.1-0.4。

    【设计压力与工作压力】
    1. design_pressure（设计压力）：从设计基本数据表或标题栏中读取，通常标注为"设计压力"或"Design Pressure"。
    2. working_pressure（工作压力）：从设计基本数据表或标题栏中读取，通常标注为"工作压力"或"Operating Pressure"或"操作压力"。
    3. design_pressure 为 Quantity 格式（value/unit/raw_text），仅存单一值。
    4. working_pressure 为 PositionalQuantity 格式，支持塔顶/塔底/塔侧分位：
       - top：塔顶工作压力（Quantity格式）
       - bottom：塔底/塔釜工作压力（Quantity格式）
       - side：塔侧工作压力（Quantity格式，较少见，无则填null）
       - raw_text：保留图纸原始标注全文，如"X(顶)/Y(底) MPaG"
    5. 若图纸仅标注一个统一值，top、bottom、side 三个位置均填入该值；若明确区分塔顶塔底，分别填入 top 和 bottom。

    【设计温度与工作温度】
    1. design_temperature（设计温度）：从设计基本数据表或标题栏中读取，通常标注为"设计温度"或"Design Temperature"。
    2. working_temperature（工作温度）：从设计基本数据表或标题栏中读取，通常标注为"工作温度"或"Operating Temperature"或"操作温度"。
    3. design_temperature 为 Quantity 格式（value/unit/raw_text），仅存单一值。
    4. working_temperature 为 PositionalQuantity 格式，支持塔顶/塔底/塔侧分位：
       - top：塔顶工作温度（Quantity格式）
       - bottom：塔底/塔釜工作温度（Quantity格式）
       - side：塔侧工作温度（Quantity格式，较少见，无则填null）
       - raw_text：保留图纸原始标注全文，如"X(顶)/Y(底) ℃"
    5. 若图纸仅标注一个统一值，top、bottom、side 三个位置均填入该值；若明确区分塔顶塔底，分别填入 top 和 bottom。

    【管口角色】
    - 进料、进口、水进口、余液进口、气相入口等按语义选 feed 或 vapor_inlet。
    - 出料、出口、水出口、余液出口、再沸液出口等按语义选 draw 或 bottom_outlet。
    - 回流液入口为 reflux；放空/排气为 vent；测温/压力/液位/检查孔为 instrument；人孔为 manway。
    - 不确定时 nozzle_role=unknown，并保留 service_description 原文。
    - service_description 填写管口表中的用途原文，如"进料口""循环水进口"等。
    - flange_standard、face_type、pipe_size 从管口表对应列读取，缺失填空字符串。

    【管口编号拆分】
    - 管口表中如"a1-a3"表示多个同用途管口，必须拆分为独立的 nozzle_id 条目：a1、a2、a3 各一条。
    - 每条管口记录必须有自己的 elevation（标高）和 between（定位引用），不得合并。
    - 例如：管口表"a1-a3 进料口"，主视图标注"a1 EL+XXXXX、a2 EL+XXXXX、a3 EL+XXXXX"，则输出三条独立记录。
    - nozzle_id 即为管口表中的符号，如"a1"。

    【管口定位引用 between】
    - between 描述管口在塔内件之间的位置，统一格式为 {"type": "tray"|"packing", "refs": [编号列表]}。
    - type 为 "tray" 时，refs 填塔板号列表，表示管口位于这些塔板之间或附近；如 [10, 11] 表示管口在10#和11#塔板之间。
    - type 为 "packing" 时，refs 填填料段编号列表，表示管口位于这些填料段之间；如 [1, 2] 表示管口在第1段和第2段填料之间。
    - 若管口不在任何内件之间（如塔顶气相出口、塔底液相出口、裙座管口），refs 填空数组 []。
    - 板式塔的 between.type 固定为 "tray"，填料塔的 between.type 固定为 "packing"。
    """

_COMMON_OUTPUT = """
    【输出要求】
    1. 仅输出 JSON，不要输出 markdown，不要解释。
    2. 顶层必须直接是下面的数据模型，所有字段必须存在。

    {
      "source_image_id": "",
      "column_type": "__COLUMN_TYPE__",
      "info": {
        "equipment_tag": "",
        "equipment_name": "",
        "drawing_name": ""
      },
      "nominal_diameter": {"value": null, "unit": "mm", "raw_text": ""},
      "total_height": {"value": null, "unit": "mm", "raw_text": ""},
      "design_pressure": {"value": null, "unit": "MPa", "raw_text": ""},
      "working_pressure": {
        "top": {"value": null, "unit": "MPa", "raw_text": ""},
        "bottom": {"value": null, "unit": "MPa", "raw_text": ""},
        "side": null,
        "raw_text": ""
      },
      "design_temperature": {"value": null, "unit": "℃", "raw_text": ""},
      "working_temperature": {
        "top": {"value": null, "unit": "℃", "raw_text": ""},
        "bottom": {"value": null, "unit": "℃", "raw_text": ""},
        "side": null,
        "raw_text": ""
      },
      "diameter_sections": [
        {
          "section_id": "S1",
          "diameter": {"value": null, "unit": "mm", "raw_text": ""},
          "elevation_top": {"value": null, "unit": "mm", "raw_text": ""},
          "elevation_bottom": {"value": null, "unit": "mm", "raw_text": ""},
          "evidence": "",
          "confidence": 0.0
        }
      ],
      "count": null,
      "numbering_direction": "top_to_bottom|bottom_to_top|unknown",
      "internals_sections": [
        {
          "from_no": null,
          "to_no": null,
          "spacing": {"value": null, "unit": "mm", "raw_text": ""},
          "diameter": {"value": null, "unit": "mm", "raw_text": ""},
          "height": {"value": null, "unit": "mm", "raw_text": ""},
          "elevation_top": {"value": null, "unit": "mm", "raw_text": ""},
          "elevation_bottom": {"value": null, "unit": "mm", "raw_text": ""},
          "evidence": "",
          "confidence": 0.0
        }
      ],
      "nozzles": [
        {
          "nozzle_id": "",
          "service_description": "",
          "nozzle_role": "feed|draw|reflux|vapor_inlet|bottom_outlet|material_inlet|material_outlet|utility_inlet|utility_outlet|utility|vent|drain|manway|instrument|other|unknown",
          "nominal_size": "",
          "flange_standard": "",
          "face_type": "",
          "pipe_size": "",
          "elevation": {"value": null, "unit": "mm", "raw_text": ""},
          "between": {"type": "__BETWEEN_TYPE__", "refs": []},
          "evidence": "",
          "confidence": 0.0
        }
      ],
      "warnings": []
    }
    """

_COMMON_CHECKLIST = """
    【自检清单】
    □ 是否只输出一个 JSON 对象
    □ 设计压力和工作压力是否从设计基本数据表或标题栏中提取
    □ 设计温度和工作温度是否从设计基本数据表或标题栏中提取
    □ 管口用途是否来自管口表或主视图标注，而不是零件明细表序号
    □ 不确定信息是否写入 warnings
    □ 管口编号是否已拆分为独立条目（如 a1-a3 拆为 a1、a2、a3）
    """


def _build_common(sections: list[str], context: PromptContext, builder: PromptBuilder) -> str:
    if context.has_image_size:
        sections.append(builder.build_image_size_section(context.image_size))
    source_id = ""
    if context.extra:
        source_id = str(
            context.extra.get("column_id")
            or context.extra.get("source_image_id")
            or context.extra.get("id")
            or ""
        ).strip()
    if source_id:
        sections.append(f"【任务上下文】\n当前图像对应的精馏塔样本 id 为：{source_id}。")
    return "\n".join(s for s in sections if s)


def _build_common_schemas() -> tuple[dict, dict, dict, dict, dict, dict, dict]:
    quantity_schema = {
        "type": "object",
        "required": ["value", "unit", "raw_text"],
        "properties": {
            "value": {"type": ["number", "null"]},
            "unit": {"type": "string"},
            "raw_text": {"type": "string"},
        },
    }
    positional_quantity_schema = {
        "type": "object",
        "required": ["top", "bottom", "side", "raw_text"],
        "properties": {
            "top": quantity_schema,
            "bottom": quantity_schema,
            "side": quantity_schema,
            "raw_text": {"type": "string"},
        },
    }
    info_schema = {
        "type": "object",
        "required": [
            "equipment_tag",
            "equipment_name",
            "drawing_name",
        ],
        "properties": {
            "equipment_tag": {"type": "string"},
            "equipment_name": {"type": "string"},
            "drawing_name": {"type": "string"},
        },
    }
    diameter_section_schema = {
        "type": "object",
        "required": [
            "section_id",
            "diameter",
            "elevation_top",
            "elevation_bottom",
            "evidence",
            "confidence",
        ],
        "properties": {
            "section_id": {"type": "string"},
            "diameter": quantity_schema,
            "elevation_top": quantity_schema,
            "elevation_bottom": quantity_schema,
            "evidence": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
    }
    between_ref_schema = {
        "type": "object",
        "required": ["type", "refs"],
        "properties": {
            "type": {"type": "string", "enum": ["tray", "packing"]},
            "refs": {"type": "array", "items": {"type": "integer"}},
        },
    }
    port_schema = {
        "type": "object",
        "required": [
            "nozzle_id",
            "service_description",
            "nozzle_role",
            "nominal_size",
            "flange_standard",
            "face_type",
            "pipe_size",
            "elevation",
            "between",
            "evidence",
            "confidence",
        ],
        "properties": {
            "nozzle_id": {"type": "string"},
            "service_description": {"type": "string"},
            "nozzle_role": {
                "type": "string",
                "enum": [
                    "feed",
                    "draw",
                    "reflux",
                    "vapor_inlet",
                    "bottom_outlet",
                    "material_inlet",
                    "material_outlet",
                    "utility_inlet",
                    "utility_outlet",
                    "utility",
                    "vent",
                    "drain",
                    "manway",
                    "instrument",
                    "other",
                    "unknown",
                ],
            },
            "nominal_size": {"type": "string"},
            "flange_standard": {"type": "string"},
            "face_type": {"type": "string"},
            "pipe_size": {"type": "string"},
            "elevation": quantity_schema,
            "between": between_ref_schema,
            "evidence": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
    }
    column_section_schema = {
        "type": "object",
        "required": [
            "from_no",
            "to_no",
            "spacing",
            "diameter",
            "height",
            "elevation_top",
            "elevation_bottom",
            "evidence",
            "confidence",
        ],
        "properties": {
            "from_no": {"type": ["integer", "null"]},
            "to_no": {"type": ["integer", "null"]},
            "spacing": quantity_schema,
            "diameter": quantity_schema,
            "height": quantity_schema,
            "elevation_top": quantity_schema,
            "elevation_bottom": quantity_schema,
            "evidence": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
    }
    return (
        quantity_schema,
        positional_quantity_schema,
        info_schema,
        diameter_section_schema,
        between_ref_schema,
        port_schema,
        column_section_schema,
    )


@register_prompt("column_assembly", "v1")
class ColumnAssemblyPromptBuilderV1(PromptBuilder):
    expert_type = "column_assembly"
    version = "v1"
    description = "V1 板式塔装配图信息提取：抽取塔板数、板间距、塔径分段和管口定位"

    _ROLE = """
    你是一个专业的板式塔装配图信息提取专家。你的任务是从板式塔装配图、主视图、剖视图、设计基本数据表、管口表、明细表和标题栏中提取结构化设计信息。
    该塔为板式塔（Tray Column），内部构件为塔板/塔盘，不存在填料段。
    """

    _RULES = _COMMON_RULES + """
    【板式塔抽取】
    1. count：读取最大可见塔板号或表格明确塔板数；不要把零件序号当塔板号。
    2. numbering：根据塔板号随高度变化判断 top_to_bottom / bottom_to_top；无法判断为 unknown。
    3. sections：从板间距尺寸或标注提取，可按塔板范围分段。每段填写 from_no（起始塔板号）、to_no（终止塔板号）、spacing（板间距）。
    4. 管口定位：between.type 固定为 "tray"；between.refs 填管口附近或相邻的塔板号，如管口在10#和11#塔板之间则 refs 为 [10, 11]；仅一块塔板附近则填一个编号如 [1]；塔顶/塔底/裙座管口填 []。
    """

    _OUTPUT_FORMAT = _COMMON_OUTPUT.replace("__COLUMN_TYPE__", "tray").replace("__BETWEEN_TYPE__", "tray")

    _CHECKLIST = _COMMON_CHECKLIST + """
    □ 是否提取 count（塔板数）、板间距和管口对应塔板号
    """

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]
        sections.extend([self._RULES, self._OUTPUT_FORMAT, self._CHECKLIST])
        return _build_common(sections, context, self)

    def get_output_schema(self) -> dict[str, Any]:
        (
            quantity_schema,
            positional_quantity_schema,
            info_schema,
            diameter_section_schema,
            between_ref_schema,
            port_schema,
            column_section_schema,
        ) = _build_common_schemas()
        return {
            "type": "object",
            "required": [
                "source_image_id",
                "column_type",
                "info",
                "nominal_diameter",
                "total_height",
                "design_pressure",
                "working_pressure",
                "design_temperature",
                "working_temperature",
                "diameter_sections",
                "count",
                "numbering_direction",
                "internals_sections",
                "nozzles",
                "warnings",
            ],
            "properties": {
                "source_image_id": {"type": "string"},
                "column_type": {"type": "string", "enum": ["tray"]},
                "info": info_schema,
                "nominal_diameter": quantity_schema,
                "total_height": quantity_schema,
                "design_pressure": quantity_schema,
                "working_pressure": positional_quantity_schema,
                "design_temperature": quantity_schema,
                "working_temperature": positional_quantity_schema,
                "diameter_sections": {
                    "type": "array",
                    "items": diameter_section_schema,
                },
                "count": {"type": ["integer", "null"]},
                "numbering_direction": {
                    "type": "string",
                    "enum": ["top_to_bottom", "bottom_to_top", "unknown"],
                },
                "internals_sections": {
                    "type": "array",
                    "items": column_section_schema,
                },
                "nozzles": {"type": "array", "items": port_schema},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
        }


@register_prompt("column_assembly", "v1.1")
class ColumnAssemblyPromptBuilderV1_1(PromptBuilder):
    expert_type = "column_assembly"
    version = "v1.1"
    description = "V1.1 板式塔装配图信息提取（精简版）：仅包含角色定义、目标与输出格式"

    _ROLE = """
    你是一个专业的板式塔装配图信息提取专家。你的任务是从板式塔装配图、主视图、剖视图、设计基本数据表、管口表、明细表和标题栏中提取结构化设计信息。
    该塔为板式塔（Tray Column），内部构件为塔板/塔盘，不存在填料段。
    """

    _GOAL = """
    【目标】
    从板式塔装配图中提取以下结构化设计信息：
    1. 设备基本信息：设备位号、名称、图名。
    2. 塔体几何参数：公称直径、总高度、塔径分段（各段直径及上下标高）。
    3. 工艺参数：设计压力/温度、工作压力/温度（区分塔顶、塔底、塔侧）。
    4. 塔板信息：塔板数、编号方向（自上而下/自下而上）、塔板分段（起止塔板号、板间距、塔径、高度及标高）。
    5. 管口信息：管口编号、用途描述、管口角色、法兰与尺寸信息、标高、所在塔板间位置。
    6. 不确定或冲突信息写入 warnings。
    """

    _OUTPUT_FORMAT = _COMMON_OUTPUT.replace("__COLUMN_TYPE__", "tray").replace("__BETWEEN_TYPE__", "tray")

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE, self._GOAL, self._OUTPUT_FORMAT]
        return _build_common(sections, context, self)

    def get_output_schema(self) -> dict[str, Any]:
        (
            quantity_schema,
            positional_quantity_schema,
            info_schema,
            diameter_section_schema,
            between_ref_schema,
            port_schema,
            column_section_schema,
        ) = _build_common_schemas()
        return {
            "type": "object",
            "required": [
                "source_image_id",
                "column_type",
                "info",
                "nominal_diameter",
                "total_height",
                "design_pressure",
                "working_pressure",
                "design_temperature",
                "working_temperature",
                "diameter_sections",
                "count",
                "numbering_direction",
                "internals_sections",
                "nozzles",
                "warnings",
            ],
            "properties": {
                "source_image_id": {"type": "string"},
                "column_type": {"type": "string", "enum": ["tray"]},
                "info": info_schema,
                "nominal_diameter": quantity_schema,
                "total_height": quantity_schema,
                "design_pressure": quantity_schema,
                "working_pressure": positional_quantity_schema,
                "design_temperature": quantity_schema,
                "working_temperature": positional_quantity_schema,
                "diameter_sections": {
                    "type": "array",
                    "items": diameter_section_schema,
                },
                "count": {"type": ["integer", "null"]},
                "numbering_direction": {
                    "type": "string",
                    "enum": ["top_to_bottom", "bottom_to_top", "unknown"],
                },
                "internals_sections": {
                    "type": "array",
                    "items": column_section_schema,
                },
                "nozzles": {"type": "array", "items": port_schema},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
        }


@register_prompt("column_assembly", "v2.1")
class ColumnAssemblyPromptBuilderV2_1(PromptBuilder):
    expert_type = "column_assembly"
    version = "v2.1"
    description = "V2.1 填料塔装配图信息提取（精简版）：仅包含角色定义、目标与输出格式"

    _ROLE = """
    你是一个专业的填料塔装配图信息提取专家。你的任务是从填料塔装配图、主视图、剖视图、设计基本数据表、管口表、明细表和标题栏中提取结构化设计信息。
    该塔为填料塔（Packed Column），内部构件为填料床段，不存在塔板/塔盘。
    """

    _GOAL = """
    【目标】
    从填料塔装配图中提取以下结构化设计信息：
    1. 设备基本信息：设备位号、名称、图名。
    2. 塔体几何参数：公称直径、总高度、塔径分段（各段直径及上下标高）。
    3. 工艺参数：设计压力/温度、工作压力/温度（区分塔顶、塔底、塔侧）。
    4. 填料段信息：填料段数、编号方向、各填料段（段号、高度、塔径、上下标高）。
    5. 管口信息：管口编号、用途描述、管口角色、法兰与尺寸信息、标高、所在填料段间位置。
    6. 不确定或冲突信息写入 warnings。
    """

    _OUTPUT_FORMAT = _COMMON_OUTPUT.replace("__COLUMN_TYPE__", "packed").replace("__BETWEEN_TYPE__", "packing")

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE, self._GOAL, self._OUTPUT_FORMAT]
        return _build_common(sections, context, self)

    def get_output_schema(self) -> dict[str, Any]:
        (
            quantity_schema,
            positional_quantity_schema,
            info_schema,
            diameter_section_schema,
            between_ref_schema,
            port_schema,
            column_section_schema,
        ) = _build_common_schemas()
        return {
            "type": "object",
            "required": [
                "source_image_id",
                "column_type",
                "info",
                "nominal_diameter",
                "total_height",
                "design_pressure",
                "working_pressure",
                "design_temperature",
                "working_temperature",
                "diameter_sections",
                "count",
                "numbering_direction",
                "internals_sections",
                "nozzles",
                "warnings",
            ],
            "properties": {
                "source_image_id": {"type": "string"},
                "column_type": {"type": "string", "enum": ["packed"]},
                "info": info_schema,
                "nominal_diameter": quantity_schema,
                "total_height": quantity_schema,
                "design_pressure": quantity_schema,
                "working_pressure": positional_quantity_schema,
                "design_temperature": quantity_schema,
                "working_temperature": positional_quantity_schema,
                "diameter_sections": {
                    "type": "array",
                    "items": diameter_section_schema,
                },
                "count": {"type": ["integer", "null"]},
                "numbering_direction": {
                    "type": "string",
                    "enum": ["top_to_bottom", "bottom_to_top", "unknown"],
                },
                "internals_sections": {
                    "type": "array",
                    "items": column_section_schema,
                },
                "nozzles": {"type": "array", "items": port_schema},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
        }


@register_prompt("column_assembly", "v2")
class ColumnAssemblyPromptBuilderV2(PromptBuilder):
    expert_type = "column_assembly"
    version = "v2"
    description = "V2 填料塔装配图信息提取：抽取填料段、塔径分段和管口定位"

    _ROLE = """
    你是一个专业的填料塔装配图信息提取专家。你的任务是从填料塔装配图、主视图、剖视图、设计基本数据表、管口表、明细表和标题栏中提取结构化设计信息。
    该塔为填料塔（Packed Column），内部构件为填料床段，不存在塔板/塔盘。
    """

    _RULES = _COMMON_RULES + """
    【填料塔抽取】
    1. internals_sections 按自上而下编号，每段 from_no 填写段号。
    2. 每段填料输出 height、diameter、上下标高；塔径优先读取主视图直径尺寸、标题栏 DN 或明细表筒体/变径段。
    3. count 优先等于识别出的填料段数量；若设计表明确给出段数，以明确表格为准并解释差异。
    4. 管口定位：between.type 固定为 "packing"；between.refs 填管口相邻的填料段编号，如管口在第1段和第2段填料之间则 refs 为 [1, 2]；塔顶/塔底/裙座管口填 []。
    """

    _OUTPUT_FORMAT = _COMMON_OUTPUT.replace("__COLUMN_TYPE__", "packed").replace("__BETWEEN_TYPE__", "packing")

    _CHECKLIST = _COMMON_CHECKLIST + """
    □ 是否提取 internals_sections（填料段）、每段高度/塔径和管口对应段间界面
    """

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]
        sections.extend([self._RULES, self._OUTPUT_FORMAT, self._CHECKLIST])
        return _build_common(sections, context, self)

    def get_output_schema(self) -> dict[str, Any]:
        (
            quantity_schema,
            positional_quantity_schema,
            info_schema,
            diameter_section_schema,
            between_ref_schema,
            port_schema,
            column_section_schema,
        ) = _build_common_schemas()
        return {
            "type": "object",
            "required": [
                "source_image_id",
                "column_type",
                "info",
                "nominal_diameter",
                "total_height",
                "design_pressure",
                "working_pressure",
                "design_temperature",
                "working_temperature",
                "diameter_sections",
                "count",
                "numbering_direction",
                "internals_sections",
                "nozzles",
                "warnings",
            ],
            "properties": {
                "source_image_id": {"type": "string"},
                "column_type": {"type": "string", "enum": ["packed"]},
                "info": info_schema,
                "nominal_diameter": quantity_schema,
                "total_height": quantity_schema,
                "design_pressure": quantity_schema,
                "working_pressure": positional_quantity_schema,
                "design_temperature": quantity_schema,
                "working_temperature": positional_quantity_schema,
                "diameter_sections": {
                    "type": "array",
                    "items": diameter_section_schema,
                },
                "count": {"type": ["integer", "null"]},
                "numbering_direction": {
                    "type": "string",
                    "enum": ["top_to_bottom", "bottom_to_top", "unknown"],
                },
                "internals_sections": {
                    "type": "array",
                    "items": column_section_schema,
                },
                "nozzles": {"type": "array", "items": port_schema},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
        }
