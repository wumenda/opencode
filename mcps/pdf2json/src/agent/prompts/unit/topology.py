
from typing import Any

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt


@register_prompt("topology", "v1")
class TopologyPromptBuilderV1(PromptBuilder):
    expert_type = "topology"
    version = "v1"
    description = "基础版（含端口+坐标）"

    _ROLE = """
        你是 PFD 拓扑提取专家。你的任务是分析 化工PFD（工艺流程图）图纸，提取其中的拓扑关系。
        拓扑关系是一个有向图，由节点和边组成：
        - 节点包括设备节点（泵、换热器、反应器、塔、容器等）和边界节点（界区进料、界区出料、跨图进料、跨图出料）
        - 每个节点包含若干端口（port），端口是管线与节点外轮廓的接触点，物料通过端口流入/流出节点
        - 边表示节点之间的流股连接，从 source_node_id 指向 target_node_id，方向由箭头决定
        - 边上携带流股属性：流股编号、物料名称、相态、温度、压力、流量等

        核心原则：
        1. 箭头方向决定边的方向：箭头指向 = target_node_id 方向
        2. 每条边连接同一连续管线上相邻的两个节点，禁止跨过中间节点直连
        3. 节点与端口完全由你从图纸上识别，不依赖任何外部上下文
        """

    _NODE_TYPES = """
        【节点类型定义】

        一、设备节点（equipment_node）
        equipment_type 只能使用以下枚举值：
        - pump / compressor / heat_exchanger / reactor / distillation_column
        - vessel / tank / furnace / cooler / heater / mixer / separator / other

        设备节点字段：
        - id: 唯一标识，格式 equip_1, equip_2, ...
        - name: 设备中文名称（如"进料泵"）
        - tag: 设备位号（如"P-0101"），从图纸上读取
        - equipment_type: 设备类型枚举值
        - bbox: 设备图形的外接矩形框 [x_min, y_min, x_max, y_max]，归一化坐标（0~1），用于定位设备在图纸中的位置
        - ports: 端口数组（见端口定义）

        二、边界节点（boundary_node）
        表示流程图的边界进出点：
        - boundary_in: 界区进料（从外部进入本图）
        - boundary_out: 界区出料（从本图流出到外部）
        - cross_drawing_in: 跨图进料（从其他图纸接入）
        - cross_drawing_out: 跨图出料（接到其他图纸）

        边界节点字段：
        - id: 唯一标识，格式 bn_1, bn_2, ...
        - label: 边界标签文字（如"来自V-102"）
        - boundary_type: 边界类型枚举值
        - equipment_tag: 跨图边界节点引用的设备位号列表（如["V-0101"]），仅 cross_drawing_in/cross_drawing_out 需要
        - description: 补充描述
        - bbox: 边界标注区域的外接矩形框 [x_min, y_min, x_max, y_max]，归一化坐标（0~1）
        - ports: 端口数组（见端口定义）

        三、端口（port）
        端口字段：
        - id: 端口 id，按 {{节点id}}_{{in|out|unk}}_{{序号}} 规则生成，例如 equip_1_in_1
        - direction: 端口方向，仅限 "input" / "output" / "unknown"
        - category: 端口类别，仅限 "process" / "utility"
        - label: 端口标签（可空）
        - position: 端口在图纸中的位置 [x, y]，归一化坐标（0~1），表示管线与节点外轮廓的接触点

        边界方向约束：
        - boundary_in / cross_drawing_in 只能作为 source_node_id
        - boundary_out / cross_drawing_out 只能作为 target_node_id
        """

    _EDGE_DEFINITION = """
        【边（流股连接）定义】

        边表示从一个节点到另一个节点的物料流股连接。

        边字段：
        - id: 唯一标识，格式 edge_1, edge_2, ...
        - source_node_id: 起始节点 id（物料流出方）
        - target_node_id: 目标节点 id（物料流入方）
        - stream_number: 流股编号（图中菱形标识中标注的数字编号，如"1"、"81003"等）
        - stream_name: 流股名称（如"进料"、"塔顶产品"）
        - medium: 介质名称（如"原油"、"蒸汽"）
        - condition: 物料属性
            - temperature: 温度（℃），图中可见时填写，可为单值（如25.0）或范围字符串（如"20~70"）
            - pressure: 压力（MPa），图中可见时填写，可为单值或范围字符串
            - mass_flow: 质量流量（kg/h），图中可见时填写，可为单值或范围字符串
            - volume_flow: 体积流量（m³/h），图中可见时填写，可为单值或范围字符串
            - mole_flow: 摩尔流量（kmol/h），图中可见时填写，可为单值或范围字符串
            - phase: 相态枚举值，仅限以下值：
              "liquid" | "liquid_gas" | "liquid_vapor" | "liquid_gas_vapor" |
              "vapor" | "two_phase" | "gas" | "solid" | "unknown"
            - composition: 组成（组分名→质量/摩尔分数），图中可见时填写
        """

    _DECISION_FLOW = """
        【提取流程——逐条管线执行】

        步骤1：识别所有设备节点与其端口
          - 扫描图纸中的设备图形（矩形、圆形、塔形等工艺设备符号）
          - 读取设备位号（如P-0101、E-0201、T-0301）
          - 判断设备类型
          - 为每个设备识别端口（管线与设备外轮廓的接触点），生成端口 id 和 position

        步骤2：识别所有边界节点与其端口
          - 找到图纸边缘的进料/出料标注
          - 识别跨图连接标记（通常带箭头和来源/去向说明）
          - 判断边界类型（boundary_in/out, cross_drawing_in/out）
          - 为每个边界节点生成端口 id 和 position

        步骤3：逐条管线提取连接
          - 找到每条可见的工艺实线（粗黑实线或带箭头实线）
          - 确定箭头方向：箭头指向 = target_node_id 方向
          - 沿管线追踪到相邻节点，确定 source_node_id 和 target_node_id
          - 读取管线旁的流股编号、物料属性等信息

        步骤4：填写边属性
          - stream_number: 管线旁标注的数字编号
          - condition: 管线旁标注的温度、压力、流量等数值
          - phase: 根据管线旁相态标注或工艺常识判断
          - 图中不可见的信息留空或填默认值
        """

    _HARD_CONSTRAINTS = """
        【硬约束——违反任一条则输出无效】

        1. 箭头方向为最高优先级证据，禁止输出与可见箭头方向相反的边。
        2. 每条边的 source_node_id 和 target_node_id 必须是已识别的设备节点或边界节点的 id，禁止编造节点。
        3. 每条边连接同一连续管线上相邻的两个节点，禁止跨过中间节点直连远端。
        4. boundary_in / cross_drawing_in 只能作为 source_node_id；boundary_out / cross_drawing_out 只能作为 target_node_id。
        5. 视觉交叉不等于连通，没有连续实线证据时不输出边。
        6. phase 只能使用规定的英文枚举值，禁止使用中文。
        7. 每个设备节点和边界节点必须输出 bbox（归一化坐标 [x_min, y_min, x_max, y_max]）；每个端口必须输出 position（归一化坐标 [x, y]）。
        """

    _EXCLUDED_LINES = """
        【排除线型】
        以下不是工艺管线，禁止输出对应的边：
        - 设备内部线
        - 仪表/控制信号虚线
        - 文字下划线
        - 设备位号引线
        - 公用工程小支线（若不影响主物料流向）
        """

    _MISS_CHECK = """
        【漏连检查】
        输出前做以下检查：
        1. 每个设备节点是否至少有一条入边或出边（孤立设备通常不正常）
        2. 每个 boundary_in 是否作为 source_node_id 出现在至少一条边中
        3. 每个 boundary_out 是否作为 target_node_id 出现在至少一条边中
        4. 是否有可见管线被遗漏（特别是分支管线）
        5. 箭头方向是否与边的 source_node_id/target_node_id 一致
        6. 边界节点的方向约束是否满足
        7. 每个设备节点和边界节点是否都输出了 bbox
        8. 每个端口是否都输出了 position
        """

    _OUTPUT_FORMAT = """
        【输出要求】
        直接输出纯 JSON，禁止 markdown，禁止解释文字。

        direction 取值：input / output / unknown
        category 取值：process / utility

        {{
          "equipment_nodes": [
            {{
              "id": "equip_1",
              "name": "进料泵",
              "tag": "P-0101",
              "equipment_type": "pump",
              "bbox": [0.12, 0.34, 0.18, 0.42],
              "ports": [
                {{
                  "id": "equip_1_in_1",
                  "direction": "input",
                  "category": "process",
                  "label": "",
                  "position": [0.12, 0.38]
                }},
                {{
                  "id": "equip_1_out_1",
                  "direction": "output",
                  "category": "process",
                  "label": "",
                  "position": [0.18, 0.38]
                }}
              ]
            }},
            {{
              "id": "equip_2",
              "name": "换热器",
              "tag": "E-0201",
              "equipment_type": "heat_exchanger",
              "bbox": [0.30, 0.30, 0.40, 0.40],
              "ports": [
                {{
                  "id": "equip_2_in_1",
                  "direction": "input",
                  "category": "process",
                  "label": "",
                  "position": [0.30, 0.35]
                }},
                {{
                  "id": "equip_2_out_1",
                  "direction": "output",
                  "category": "process",
                  "label": "",
                  "position": [0.40, 0.35]
                }}
              ]
            }}
          ],
          "boundary_nodes": [
            {{
              "id": "bn_1",
              "label": "原油进料",
              "boundary_type": "boundary_in",
              "equipment_tag": [],
              "description": "来自罐区",
              "bbox": [0.02, 0.35, 0.06, 0.39],
              "ports": [
                {{
                  "id": "bn_1_out_1",
                  "direction": "output",
                  "category": "process",
                  "label": "",
                  "position": [0.06, 0.37]
                }}
              ]
            }},
            {{
              "id": "bn_2",
              "label": "产品出料",
              "boundary_type": "boundary_out",
              "equipment_tag": [],
              "description": "去下游装置",
              "bbox": [0.92, 0.35, 0.96, 0.39],
              "ports": [
                {{
                  "id": "bn_2_in_1",
                  "direction": "input",
                  "category": "process",
                  "label": "",
                  "position": [0.92, 0.37]
                }}
              ]
            }},
            {{
              "id": "bn_3",
              "label": "来自PFD-0104 P-81002",
              "boundary_type": "cross_drawing_in",
              "equipment_tag": ["P-81002"],
              "description": "原料至V-XXX",
              "bbox": [0.02, 0.50, 0.06, 0.54],
              "ports": [
                {{
                  "id": "bn_3_in_1",
                  "direction": "input",
                  "category": "process",
                  "label": "",
                  "position": [0.02, 0.52]
                }},
                {{
                  "id": "bn_3_out_1",
                  "direction": "output",
                  "category": "process",
                  "label": "",
                  "position": [0.06, 0.52]
                }}
              ]
            }}
          ],
          "edges": [
            {{
              "id": "edge_1",
              "source_node_id": "bn_1",
              "target_node_id": "equip_1",
              "stream_number": "1",
              "stream_name": "原油进料",
              "medium": "原油",
              "condition": {{
                "temperature": 25.0,
                "pressure": 0.3,
                "mass_flow": 50000.0,
                "volume_flow": null,
                "mole_flow": null,
                "phase": "liquid",
                "composition": {{}}
              }}
            }},
            {{
              "id": "edge_2",
              "source_node_id": "equip_1",
              "target_node_id": "equip_2",
              "stream_number": "2",
              "stream_name": "",
              "medium": "",
              "condition": {{
                "temperature": null,
                "pressure": null,
                "mass_flow": null,
                "volume_flow": null,
                "mole_flow": null,
                "phase": "unknown",
                "composition": {{}}
              }}
            }},
            {{
              "id": "edge_3",
              "source_node_id": "equip_2",
              "target_node_id": "bn_2",
              "stream_number": "3",
              "stream_name": "产品出料",
              "medium": "",
              "condition": {{
                "temperature": 180.0,
                "pressure": 0.1,
                "mass_flow": null,
                "volume_flow": null,
                "mole_flow": null,
                "phase": "vapor",
                "composition": {{}}
              }}
            }}
          ]
        }}"""

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]

        if context.has_process_description:
            sections.append(self.build_process_description_section(context.process_description))

        sections.extend(
            [
                self._NODE_TYPES,
                self._EDGE_DEFINITION,
                self._DECISION_FLOW,
                self._HARD_CONSTRAINTS,
                self._EXCLUDED_LINES,
                self._MISS_CHECK,
                self._OUTPUT_FORMAT,
            ]
        )

        return "\n".join(s for s in sections if s)

    def get_output_schema(self) -> dict[str, Any]:
        port_schema = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "direction": {"type": "string", "enum": ["input", "output", "unknown"]},
                "category": {"type": "string", "enum": ["process", "utility"]},
                "label": {"type": "string"},
                "position": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "[x, y] 归一化坐标",
                },
            },
            "required": ["id", "direction"],
        }
        bbox_schema = {
            "type": "array",
            "items": {"type": "number"},
            "description": "[x_min, y_min, x_max, y_max] 归一化坐标",
        }
        return {
            "type": "object",
            "properties": {
                "equipment_nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "tag": {"type": "string"},
                            "equipment_type": {"type": "string"},
                            "bbox": bbox_schema,
                            "ports": {"type": "array", "items": port_schema},
                        },
                        "required": ["id"],
                    },
                },
                "boundary_nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "boundary_type": {"type": "string"},
                            "equipment_tag": {"type": "array", "items": {"type": "string"}},
                            "description": {"type": "string"},
                            "bbox": bbox_schema,
                            "ports": {"type": "array", "items": port_schema},
                        },
                        "required": ["id"],
                    },
                },
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "source_node_id": {"type": "string"},
                            "target_node_id": {"type": "string"},
                            "stream_number": {"type": "string"},
                            "stream_name": {"type": "string"},
                            "medium": {"type": "string"},
                            "condition": {"type": "object"},
                        },
                        "required": ["id", "source_node_id", "target_node_id"],
                    },
                },
            },
            "required": ["equipment_nodes", "boundary_nodes", "edges"],
        }


@register_prompt("topology", "v2")
class TopologyPromptBuilderV2(PromptBuilder):
    expert_type = "topology"
    version = "v2"
    description = "带端口"

    _ROLE = """
        你是 PFD 拓扑提取专家。你的任务是分析 化工PFD（工艺流程图）图纸，提取其中的拓扑关系。
        拓扑关系是一个有向图，由节点和边组成：
        - 节点包括设备节点（泵、换热器、反应器、塔、容器、分离器、混合器等）和边界节点（界区进料、界区出料、跨图进料、跨图出料）
        - 每个节点包含若干端口（port），端口是管线与节点外轮廓的接触点，物料通过端口流入/流出节点
        - 边表示节点之间的流股连接，从 source_node_id 节点的某个端口指向 target_node_id 节点的某个端口，方向由箭头决定
        - 边上携带流股属性：流股编号、物料名称、相态、温度、压力、流量等

        核心原则：
        1. 箭头方向决定边的方向：箭头指向 = target_node_id 方向
        2. 每条边连接同一连续管线上相邻的两个节点，禁止跨过中间节点直连
        3. 边的 source_port_id / target_port_id 必须引用已识别端口的真实 id
        4. 节点与端口完全由你从图纸上识别，不依赖任何外部上下文
        """

    _NODE_TYPES = """
        【节点类型定义】

        一、设备节点（equipment_node）
        equipment_type 只能使用以下枚举值：
        - pump / compressor / heat_exchanger / reactor / distillation_column
        - vessel / tank / furnace / cooler / heater / mixer / separator / other

        设备节点字段：
        - id: 唯一标识，格式 equip_1, equip_2, ...
        - name: 设备中文名称（如"进料泵"）
        - tag: 设备位号（如"P-101"），从图纸上读取
        - equipment_type: 设备类型枚举值
        - bbox: 设备图形的外接矩形框 [x_min, y_min, x_max, y_max]，归一化坐标（0~1），用于定位设备在图纸中的位置
        - ports: 端口数组（见端口定义）

        二、边界节点（boundary_node）
        - boundary_in / boundary_out / cross_drawing_in / cross_drawing_out

        边界节点字段：
        - id: 唯一标识，格式 bn_1, bn_2, ...
        - label: 边界标签文字
        - boundary_type: 边界类型枚举值
        - equipment_tag: 跨图边界节点引用的设备位号列表，仅 cross_drawing_in/out 需要
        - description: 补充描述
        - bbox: 边界标注区域的外接矩形框 [x_min, y_min, x_max, y_max]，归一化坐标（0~1）
        - ports: 端口数组（见端口定义）

        三、端口（port）
        端口字段：
        - id: 端口 id，按 {节点id}_{in|out|unk}_{序号} 规则生成，例如 equip_1_in_1
        - direction: 端口方向，仅限 "input" / "output" / "unknown"
        - category: 端口类别，仅限 "process" / "utility"
        - label: 端口标签（可空）
        - position: 端口在图纸中的位置 [x, y]，归一化坐标（0~1），表示管线与节点外轮廓的接触点
        - orientation: 仅限 "top" / "bottom" / "left" / "right" / "unknown"（端口在设备外轮廓上的方位）
        - channel: 内部通道标识（字符串）。同一 channel 的端口在设备内部连通；不同 channel 不连通。判定规则：
          * heat_exchanger / cooler / heater / furnace（A 类）：必须多 channel，按 top↔bottom / left↔right 几何对位配对
          * mixer / separator（B/C 类）：所有 process 端口同一 channel
          * pump / compressor / tank（D 类）：单 channel 或留空
          * distillation_column（E 类）：留空，用 orientation 描述
          * 夹套 reactor / vessel：process 端口 c1、utility 端口 c2

        边界节点端口数量约束：
        - boundary_in / boundary_out: 恰好 1 个端口
        - cross_drawing_in / cross_drawing_out: 恰好 2 个端口（1 input + 1 output）
        """

    _EDGE_DEFINITION = """
        【边（流股连接）定义】

        边表示从一个节点的某个端口到另一个节点的某个端口的物料流股连接。

        边字段（完全复用 StreamEdge 数据模型，不含位置字段）：
        - id: 唯一标识，格式 edge_1, edge_2, ...
        - source_node_id: 起始节点 id（物料流出方）
        - source_port_id: 起始节点的端口 id（物料从该端口流出），必须引用 source_node_id 节点上 direction 为 "output" 或 "unknown" 的端口
        - target_node_id: 目标节点 id（物料流入方）
        - target_port_id: 目标节点的端口 id（物料从该端口流入），必须引用 target_node_id 节点上 direction 为 "input" 或 "unknown" 的端口
        - stream_number: 流股编号（图中菱形标识中标注的数字编号，如"1"、"81003"等）
        - stream_name: 流股名称（如"进料"、"塔顶产品"）
        - medium: 介质名称（如"原油"、"蒸汽"）
        - condition: 物料属性
            - temperature: 温度（℃），图中可见时填写，可为单值（如25.0）或范围字符串（如"20~70"）
            - pressure: 压力（MPa），图中可见时填写，可为单值或范围字符串
            - mass_flow: 质量流量（kg/h），图中可见时填写，可为单值或范围字符串
            - volume_flow: 体积流量（m³/h），图中可见时填写，可为单值或范围字符串
            - mole_flow: 摩尔流量（kmol/h），图中可见时填写，可为单值或范围字符串
            - phase: 相态枚举值，仅限以下值：
              "liquid" | "liquid_gas" | "liquid_vapor" | "liquid_gas_vapor" |
              "vapor" | "two_phase" | "gas" | "solid" | "unknown"
            - composition: 组成（组分名→质量/摩尔分数），图中可见时填写

        端口引用约束：
        - source_port_id 必须属于 source_node_id 节点的 ports 列表；target_port_id 必须属于 target_node_id 节点的 ports 列表
        - 若无法确定具体端口，source_port_id / target_port_id 可留空字符串 ""，但优先尝试匹配
        - 同一 source_port_id 可出现在多条边中（表示分流）
        - 同一设备内部跨 channel 的端口不可直接相连（如换热器管程入口不会经由设备内部连到壳程出口；任何由设备内部"绕回"的连接必须按 channel 配对推理）
        """

    _DECISION_FLOW = """
        【提取流程——逐条管线执行】

        步骤1：识别所有设备节点与其端口
          - 扫描图纸中的设备图形，读取设备位号、判断设备类型
          - 为每个设备识别端口（管线与设备外轮廓的接触点），生成端口 id

        步骤2：识别所有边界节点与其端口
          - 找到图纸边缘的进料/出料标注与跨图标记
          - 按边界类型生成对应数量与方向的端口

        步骤3：逐条管线追踪连接
          - 找到每条可见的工艺实线（粗黑实线或带箭头实线）
          - 确定箭头方向：箭头指向 = target_node_id 方向
          - 沿管线追踪到相邻节点，确定 source_node_id 和 target_node_id
          - 确定该管线在 source_node_id 节点上的端口 id（source_port_id）和在 target_node_id 节点上的端口 id（target_port_id）
          - 读取管线旁的流股编号、物料属性等信息

        步骤4：填写边属性
          - stream_number: 管线旁标注的数字编号
          - condition: 管线旁标注的温度、压力、流量等数值
          - phase: 根据管线旁相态标注或工艺常识判断
          - 图中不可见的信息留空或填默认值
        """

    _HARD_CONSTRAINTS = """
        【硬约束——违反任一条则输出无效】

        1. 箭头方向为最高优先级证据，禁止输出与可见箭头方向相反的边。
        2. 每条边的 source_node_id 和 target_node_id 必须是已识别的设备节点或边界节点的 id，禁止编造节点。
        3. 每条边连接同一连续管线上相邻的两个节点，禁止跨过中间节点直连远端。
        4. boundary_in / cross_drawing_in 只能作为 source_node_id；boundary_out / cross_drawing_out 只能作为 target_node_id。
        5. 视觉交叉不等于连通，没有连续实线证据时不输出边。
        6. phase 只能使用规定的英文枚举值，禁止使用中文。
        7. 每个设备节点和边界节点必须输出 bbox（归一化坐标 [x_min, y_min, x_max, y_max]）；每个端口必须输出 position（归一化坐标 [x, y]）。
        8. 端口 id 必须与 direction 一致：direction="input" → id 含 "_in_"；direction="output" → id 含 "_out_"；direction="unknown" → id 含 "_unk_"。
        9. source_port_id 必须属于 source_node_id 节点的 ports 列表；target_port_id 必须属于 target_node_id 节点的 ports 列表（或留空字符串）。
        10. 端口 direction 只能使用 "input" / "output" / "unknown"；category 只能使用 "process" / "utility"；orientation 只能使用 "top" / "bottom" / "left" / "right" / "unknown"。
        11. 边界节点端口数量约束：boundary_in/boundary_out 恰好 1 个端口；cross_drawing_in/cross_drawing_out 恰好 2 个端口（1 input + 1 output）。
        12. 端口 channel 字段必须保留并原样透传上下文给定值；多端口非混合设备（如 heat_exchanger）至少应有 2 个 channel。
        """

    _EXCLUDED_LINES = """
        【排除线型】
        以下不是工艺管线，禁止输出对应的边：
        - 设备内部线
        - 仪表/控制信号虚线
        - 文字下划线
        - 设备位号引线
        - 公用工程小支线（若不影响主物料流向）
        """

    _MISS_CHECK = """
        【漏连检查】
        输出前做以下检查：
        1. 每个设备节点是否至少有一条入边或出边（孤立设备通常不正常）
        2. 每个 boundary_in 是否作为 source_node_id 出现在至少一条边中
        3. 每个 boundary_out 是否作为 target_node_id 出现在至少一条边中
        4. 是否有可见管线被遗漏（特别是分支管线）
        5. 箭头方向是否与边的 source_node_id/target_node_id 一致
        6. 边界节点的方向约束是否满足
        7. 每个端口 id 是否与 direction 一致（input→_in_、output→_out_、unknown→_unk_）
        8. 每条边的 source_port_id 是否属于 source_node_id 节点的 ports 列表（或为空字符串）
        9. 每条边的 target_port_id 是否属于 target_node_id 节点的 ports 列表（或为空字符串）
        10. 边界节点端口数量是否符合约束（boundary_in/out 1 个；cross_drawing_in/out 2 个）
        11. 每个端口是否输出了 orientation（top/bottom/left/right/unknown）
        12. 每个设备节点和边界节点是否都输出了 bbox
        13. 每个端口是否都输出了 position
        """

    _OUTPUT_FORMAT = """
        【输出要求】
        直接输出纯 JSON，禁止 markdown，禁止解释文字。

        direction 取值：input / output / unknown
        category 取值：process / utility
        orientation 取值：top / bottom / left / right / unknown

        {{
          "equipment_nodes": [
            {{
              "id": "equip_1",
              "name": "进料泵",
              "tag": "P-101",
              "equipment_type": "pump",
              "bbox": [0.12, 0.34, 0.18, 0.42],
              "ports": [
                {{
                  "id": "equip_1_in_1",
                  "direction": "input",
                  "category": "process",
                  "label": "",
                  "position": [0.12, 0.38],
                  "orientation": "left",
                  "channel": "c1"
                }},
                {{
                  "id": "equip_1_out_1",
                  "direction": "output",
                  "category": "process",
                  "label": "",
                  "position": [0.18, 0.38],
                  "orientation": "right",
                  "channel": "c1"
                }}
              ]
            }},
            {{
              "id": "equip_2",
              "name": "脱丙烷塔",
              "tag": "T-201",
              "equipment_type": "distillation_column",
              "bbox": [0.30, 0.20, 0.40, 0.80],
              "ports": [
                {{
                  "id": "equip_2_out_1",
                  "direction": "output",
                  "category": "process",
                  "label": "塔顶产品",
                  "position": [0.35, 0.20],
                  "orientation": "top",
                  "channel": ""
                }},
                {{
                  "id": "equip_2_in_1",
                  "direction": "input",
                  "category": "process",
                  "label": "进料",
                  "position": [0.30, 0.50],
                  "orientation": "left",
                  "channel": ""
                }},
                {{
                  "id": "equip_2_out_2",
                  "direction": "output",
                  "category": "process",
                  "label": "塔底产品",
                  "position": [0.35, 0.80],
                  "orientation": "bottom",
                  "channel": ""
                }}
              ]
            }}
          ],
          "boundary_nodes": [
            {{
              "id": "bn_1",
              "label": "原油进料",
              "boundary_type": "boundary_in",
              "equipment_tag": [],
              "description": "来自罐区",
              "bbox": [0.02, 0.35, 0.06, 0.39],
              "ports": [
                {{
                  "id": "bn_1_out_1",
                  "direction": "output",
                  "category": "process",
                  "label": "",
                  "position": [0.06, 0.37],
                  "orientation": "unknown",
                  "channel": ""
                }}
              ]
            }},
            {{
              "id": "bn_2",
              "label": "产品出料",
              "boundary_type": "boundary_out",
              "equipment_tag": [],
              "description": "去下游装置",
              "bbox": [0.92, 0.35, 0.96, 0.39],
              "ports": [
                {{
                  "id": "bn_2_in_1",
                  "direction": "input",
                  "category": "process",
                  "label": "",
                  "position": [0.92, 0.37],
                  "orientation": "unknown",
                  "channel": ""
                }}
              ]
            }},
            {{
              "id": "bn_3",
              "label": "来自PFD-0104 P-81002",
              "boundary_type": "cross_drawing_in",
              "equipment_tag": ["P-81002"],
              "description": "原料至V-XXX",
              "bbox": [0.02, 0.50, 0.06, 0.54],
              "ports": [
                {{
                  "id": "bn_3_in_1",
                  "direction": "input",
                  "category": "process",
                  "label": "",
                  "position": [0.02, 0.52],
                  "orientation": "unknown",
                  "channel": ""
                }},
                {{
                  "id": "bn_3_out_1",
                  "direction": "output",
                  "category": "process",
                  "label": "",
                  "position": [0.06, 0.52],
                  "orientation": "unknown",
                  "channel": ""
                }}
              ]
            }}
          ],
          "edges": [
            {{
              "id": "edge_1",
              "source_node_id": "bn_1",
              "source_port_id": "bn_1_out_1",
              "target_node_id": "equip_1",
              "target_port_id": "equip_1_in_1",
              "stream_number": "1",
              "stream_name": "原油进料",
              "medium": "原油",
              "condition": {{
                "temperature": 25.0,
                "pressure": 0.3,
                "mass_flow": 50000.0,
                "volume_flow": null,
                "mole_flow": null,
                "phase": "liquid",
                "composition": {{}}
              }}
            }},
            {{
              "id": "edge_2",
              "source_node_id": "equip_1",
              "source_port_id": "equip_1_out_1",
              "target_node_id": "equip_2",
              "target_port_id": "equip_2_in_1",
              "stream_number": "2",
              "stream_name": "",
              "medium": "",
              "condition": {{
                "temperature": null,
                "pressure": null,
                "mass_flow": null,
                "volume_flow": null,
                "mole_flow": null,
                "phase": "unknown",
                "composition": {{}}
              }}
            }},
            {{
              "id": "edge_3",
              "source_node_id": "equip_2",
              "source_port_id": "equip_2_out_1",
              "target_node_id": "bn_2",
              "target_port_id": "bn_2_in_1",
              "stream_number": "3",
              "stream_name": "产品出料",
              "medium": "",
              "condition": {{
                "temperature": 180.0,
                "pressure": 0.1,
                "mass_flow": null,
                "volume_flow": null,
                "mole_flow": null,
                "phase": "vapor",
                "composition": {{}}
              }}
            }},
            {{
              "id": "edge_4",
              "source_node_id": "bn_3",
              "source_port_id": "bn_3_out_1",
              "target_node_id": "equip_2",
              "target_port_id": "equip_2_in_1",
              "stream_number": "4",
              "stream_name": "跨图进料",
              "medium": "",
              "condition": {{
                "temperature": null,
                "pressure": null,
                "mass_flow": null,
                "volume_flow": null,
                "mole_flow": null,
                "phase": "unknown",
                "composition": {{}}
              }}
            }}
          ]
        }}"""

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]

        if context.has_process_description:
            sections.append(self.build_process_description_section(context.process_description))

        sections.extend(
            [
                self._NODE_TYPES,
                self._EDGE_DEFINITION,
                self._DECISION_FLOW,
                self._HARD_CONSTRAINTS,
                self._EXCLUDED_LINES,
                self._MISS_CHECK,
                self._OUTPUT_FORMAT,
            ]
        )

        return "\n".join(s for s in sections if s)

    def get_output_schema(self) -> dict[str, Any]:
        port_schema = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "direction": {"type": "string", "enum": ["input", "output", "unknown"]},
                "category": {"type": "string", "enum": ["process", "utility"]},
                "label": {"type": "string"},
                "position": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "[x, y] 归一化坐标",
                },
                "orientation": {
                    "type": "string",
                    "enum": ["top", "bottom", "left", "right", "unknown"],
                },
                "channel": {"type": "string"},
            },
            "required": ["id", "direction"],
        }
        bbox_schema = {
            "type": "array",
            "items": {"type": "number"},
            "description": "[x_min, y_min, x_max, y_max] 归一化坐标",
        }
        return {
            "type": "object",
            "properties": {
                "equipment_nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "tag": {"type": "string"},
                            "equipment_type": {"type": "string"},
                            "bbox": bbox_schema,
                            "ports": {"type": "array", "items": port_schema},
                        },
                        "required": ["id"],
                    },
                },
                "boundary_nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "boundary_type": {"type": "string"},
                            "equipment_tag": {"type": "array", "items": {"type": "string"}},
                            "description": {"type": "string"},
                            "bbox": bbox_schema,
                            "ports": {"type": "array", "items": port_schema},
                        },
                        "required": ["id"],
                    },
                },
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "source_node_id": {"type": "string"},
                            "source_port_id": {"type": "string"},
                            "target_node_id": {"type": "string"},
                            "target_port_id": {"type": "string"},
                            "stream_number": {"type": "string"},
                            "stream_name": {"type": "string"},
                            "medium": {"type": "string"},
                            "condition": {"type": "object"},
                        },
                        "required": ["id", "source_node_id", "target_node_id"],
                    },
                },
            },
            "required": ["equipment_nodes", "boundary_nodes", "edges"],
        }


@register_prompt("topology", "v3")
class TopologyPromptBuilderV3(PromptBuilder):
    expert_type = "topology"
    version = "v3"
    description = "角色+目标"

    _ROLE = """
        你是 PFD 拓扑提取专家。你的任务是分析 化工PFD（工艺流程图）图纸，提取其中的拓扑关系。
        拓扑关系是一个有向图，由节点和边组成：
        - 节点包括设备节点（泵、换热器、反应器、塔、容器等）和边界节点（界区进料、界区出料、跨图进料、跨图出料）
        - 边表示节点之间的流股连接，从 source_node_id 指向 target_node_id，方向由箭头决定
        - 边上携带流股属性：流股编号、物料名称、相态、温度、压力、流量等

        核心原则：
        1. 箭头方向决定边的方向
        2. 每条边连接同一连续管线上相邻的两个节点，禁止跨过中间节点直连
        3. 节点完全由你从图纸上识别，不依赖任何外部上下文
        """

    _NODE_TYPES = """
        【节点类型定义】

        一、设备节点（equipment_node）
        equipment_type 只能使用以下枚举值：
        - pump / compressor / heat_exchanger / reactor / distillation_column
        - vessel / tank / furnace / cooler / heater / mixer / separator / other

        设备节点字段：
        - id: 唯一标识，格式 equip_1, equip_2, ...
        - name: 设备中文名称（如"进料泵"）
        - tag: 设备位号（如"P-0101"），从图纸上读取
        - equipment_type: 设备类型枚举值
        - bbox: 设备图形的外接矩形框 [x_min, y_min, x_max, y_max]，归一化坐标（0~1），用于定位设备在图纸中的位置
        - ports: 端口数组（见端口定义）

        二、边界节点（boundary_node）
        - boundary_in / boundary_out / cross_drawing_in / cross_drawing_out

        边界节点字段：
        - id: 唯一标识，格式 bn_1, bn_2, ...
        - label: 边界标签文字
        - boundary_type: 边界类型枚举值
        - equipment_tag: 跨图边界节点引用的设备位号列表，仅 cross_drawing_in/out 需要
        - description: 补充描述
        - bbox: 边界标注区域的外接矩形框 [x_min, y_min, x_max, y_max]，归一化坐标（0~1）
        - ports: 端口数组（见端口定义）

        三、端口（port）
        端口字段：
        - id: 端口 id，按 {节点id}_{in|out|unk}_{序号} 规则生成，例如 equip_1_in_1
        - direction: 端口方向，仅限 "input" / "output" / "unknown"
        - category: 端口类别，仅限 "process" / "utility"
        - label: 端口标签（可空）
        - position: 端口在图纸中的位置 [x, y]，归一化坐标（0~1），表示管线与节点外轮廓的接触点
        - orientation: 仅限 "top" / "bottom" / "left" / "right" / "unknown"（端口在设备外轮廓上的方位）
        - channel: 内部通道标识（字符串）。同一 channel 的端口在设备内部连通；不同 channel 不连通。判定规则：
          * heat_exchanger / cooler / heater / furnace（A 类）：必须多 channel，按 top↔bottom / left↔right 几何对位配对
          * mixer / separator（B/C 类）：所有 process 端口同一 channel
          * pump / compressor / tank（D 类）：单 channel 或留空
          * distillation_column（E 类）：留空，用 orientation 描述
          * 夹套 reactor / vessel：process 端口 c1、utility 端口 c2

        边界节点端口数量约束：
        - boundary_in / boundary_out: 恰好 1 个端口
        - cross_drawing_in / cross_drawing_out: 恰好 2 个端口（1 input + 1 output）
        """

    _EDGE_DEFINITION = """
        【边（流股连接）定义】

        边表示从一个节点的某个端口到另一个节点的某个端口的物料流股连接。

        边字段（完全复用 StreamEdge 数据模型，不含位置字段）：
        - id: 唯一标识，格式 edge_1, edge_2, ...
        - source_node_id: 起始节点 id（物料流出方）
        - source_port_id: 起始节点的端口 id（物料从该端口流出），必须引用 source_node_id 节点上 direction 为 "output" 或 "unknown" 的端口
        - target_node_id: 目标节点 id（物料流入方）
        - target_port_id: 目标节点的端口 id（物料从该端口流入），必须引用 target_node_id 节点上 direction 为 "input" 或 "unknown" 的端口
        - stream_number: 流股编号（图中菱形标识中标注的数字编号，如"1"、"81003"等）
        - stream_name: 流股名称（如"进料"、"塔顶产品"）
        - medium: 介质名称（如"原油"、"蒸汽"）
        - condition: 物料属性
            - temperature: 温度（℃），图中可见时填写，可为单值（如25.0）或范围字符串（如"20~70"）
            - pressure: 压力（MPa），图中可见时填写，可为单值或范围字符串
            - mass_flow: 质量流量（kg/h），图中可见时填写，可为单值或范围字符串
            - volume_flow: 体积流量（m³/h），图中可见时填写，可为单值或范围字符串
            - mole_flow: 摩尔流量（kmol/h），图中可见时填写，可为单值或范围字符串
            - phase: 相态枚举值，仅限以下值：
              "liquid" | "liquid_gas" | "liquid_vapor" | "liquid_gas_vapor" |
              "vapor" | "two_phase" | "gas" | "solid" | "unknown"
            - composition: 组成（组分名→质量/摩尔分数），图中可见时填写

        端口引用约束：
        - source_port_id 必须属于 source_node_id 节点的 ports 列表；target_port_id 必须属于 target_node_id 节点的 ports 列表
        - 若无法确定具体端口，source_port_id / target_port_id 可留空字符串 ""，但优先尝试匹配
        - 同一 source_port_id 可出现在多条边中（表示分流）
        - 同一设备内部跨 channel 的端口不可直接相连（如换热器管程入口不会经由设备内部连到壳程出口）
        """

    _HARD_CONSTRAINTS = """
        【硬约束——违反任一条则输出无效】

        1. 箭头方向决定边的方向：箭头指向 = target_node_id 方向。
        2. 每条边的 source_node_id 和 target_node_id 必须是已识别的设备节点或边界节点的 id，禁止编造节点。
        3. 每条边连接同一连续管线上相邻的两个节点，禁止跨过中间节点直连。
        4. boundary_in / cross_drawing_in 只能作为 source_node_id；boundary_out / cross_drawing_out 只能作为 target_node_id。
        5. 每个设备节点和边界节点必须输出 bbox（归一化坐标 [x_min, y_min, x_max, y_max]）；每个端口必须输出 position（归一化坐标 [x, y]）。
        6. 端口 channel 字段必须保留并原样透传上下文给定值；多端口非混合设备（如 heat_exchanger）至少应有 2 个 channel。
        """

    _OUTPUT_FORMAT = """
        【输出要求】
        直接输出纯 JSON，禁止 markdown，禁止解释文字。

        direction 取值：input / output / unknown
        category 取值：process / utility
        orientation 取值：top / bottom / left / right / unknown

        {{
          "equipment_nodes": [
            {{
              "id": "equip_1",
              "name": "进料泵",
              "tag": "P-101",
              "equipment_type": "pump",
              "bbox": [0.12, 0.34, 0.18, 0.42],
              "ports": [
                {{
                  "id": "equip_1_in_1",
                  "direction": "input",
                  "category": "process",
                  "label": "",
                  "position": [0.12, 0.38],
                  "orientation": "left",
                  "channel": "c1"
                }},
                {{
                  "id": "equip_1_out_1",
                  "direction": "output",
                  "category": "process",
                  "label": "",
                  "position": [0.18, 0.38],
                  "orientation": "right",
                  "channel": "c1"
                }}
              ]
            }},
            {{
              "id": "equip_2",
              "name": "换热器",
              "tag": "E-201",
              "equipment_type": "heat_exchanger",
              "bbox": [0.30, 0.30, 0.40, 0.40],
              "ports": [
                {{
                  "id": "equip_2_in_1",
                  "direction": "input",
                  "category": "process",
                  "label": "",
                  "position": [0.35, 0.30],
                  "orientation": "top",
                  "channel": "c1"
                }},
                {{
                  "id": "equip_2_out_1",
                  "direction": "output",
                  "category": "process",
                  "label": "",
                  "position": [0.35, 0.40],
                  "orientation": "bottom",
                  "channel": "c1"
                }},
                {{
                  "id": "equip_2_in_2",
                  "direction": "input",
                  "category": "process",
                  "label": "",
                  "position": [0.40, 0.35],
                  "orientation": "right",
                  "channel": "c2"
                }},
                {{
                  "id": "equip_2_out_2",
                  "direction": "output",
                  "category": "process",
                  "label": "",
                  "position": [0.30, 0.35],
                  "orientation": "left",
                  "channel": "c2"
                }}
              ]
            }}
          ],
          "boundary_nodes": [
            {{
              "id": "bn_1",
              "label": "原油进料",
              "boundary_type": "boundary_in",
              "equipment_tag": [],
              "description": "来自罐区",
              "bbox": [0.02, 0.35, 0.06, 0.39],
              "ports": [
                {{
                  "id": "bn_1_out_1",
                  "direction": "output",
                  "category": "process",
                  "label": "",
                  "position": [0.06, 0.37],
                  "orientation": "unknown",
                  "channel": ""
                }}
              ]
            }},
            {{
              "id": "bn_2",
              "label": "产品出料",
              "boundary_type": "boundary_out",
              "equipment_tag": [],
              "description": "去下游装置",
              "bbox": [0.92, 0.35, 0.96, 0.39],
              "ports": [
                {{
                  "id": "bn_2_in_1",
                  "direction": "input",
                  "category": "process",
                  "label": "",
                  "position": [0.92, 0.37],
                  "orientation": "unknown",
                  "channel": ""
                }}
              ]
            }},
            {{
              "id": "bn_3",
              "label": "来自PFD-0104 P-81002",
              "boundary_type": "cross_drawing_in",
              "equipment_tag": ["P-81002"],
              "description": "原料至V-XXX",
              "bbox": [0.02, 0.50, 0.06, 0.54],
              "ports": [
                {{
                  "id": "bn_3_in_1",
                  "direction": "input",
                  "category": "process",
                  "label": "",
                  "position": [0.02, 0.52],
                  "orientation": "unknown",
                  "channel": ""
                }},
                {{
                  "id": "bn_3_out_1",
                  "direction": "output",
                  "category": "process",
                  "label": "",
                  "position": [0.06, 0.52],
                  "orientation": "unknown",
                  "channel": ""
                }}
              ]
            }}
          ],
          "edges": [
            {{
              "id": "edge_1",
              "source_node_id": "bn_1",
              "source_port_id": "bn_1_out_1",
              "target_node_id": "equip_1",
              "target_port_id": "equip_1_in_1",
              "stream_number": "1",
              "stream_name": "原油进料",
              "medium": "原油",
              "condition": {{
                "temperature": 25.0,
                "pressure": 0.3,
                "mass_flow": 50000.0,
                "volume_flow": null,
                "mole_flow": null,
                "phase": "liquid",
                "composition": {{}}
              }}
            }},
            {{
              "id": "edge_2",
              "source_node_id": "equip_1",
              "source_port_id": "equip_1_out_1",
              "target_node_id": "equip_2",
              "target_port_id": "equip_2_in_1",
              "stream_number": "2",
              "stream_name": "",
              "medium": "",
              "condition": {{
                "temperature": null,
                "pressure": null,
                "mass_flow": null,
                "volume_flow": null,
                "mole_flow": null,
                "phase": "unknown",
                "composition": {{}}
              }}
            }},
            {{
              "id": "edge_3",
              "source_node_id": "equip_2",
              "source_port_id": "equip_2_out_1",
              "target_node_id": "bn_2",
              "target_port_id": "bn_2_in_1",
              "stream_number": "3",
              "stream_name": "产品出料",
              "medium": "",
              "condition": {{
                "temperature": 180.0,
                "pressure": 0.1,
                "mass_flow": null,
                "volume_flow": null,
                "mole_flow": null,
                "phase": "vapor",
                "composition": {{}}
              }}
            }}
          ]
        }}"""

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]

        if context.has_process_description:
            sections.append(self.build_process_description_section(context.process_description))

        sections.extend([
            self._NODE_TYPES,
            self._EDGE_DEFINITION,
            self._HARD_CONSTRAINTS,
            self._OUTPUT_FORMAT,
        ])

        return "\n".join(s for s in sections if s)

    def get_output_schema(self) -> dict[str, Any]:
        port_schema = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "direction": {"type": "string", "enum": ["input", "output", "unknown"]},
                "category": {"type": "string", "enum": ["process", "utility"]},
                "label": {"type": "string"},
                "position": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "[x, y] 归一化坐标",
                },
                "orientation": {
                    "type": "string",
                    "enum": ["top", "bottom", "left", "right", "unknown"],
                },
                "channel": {"type": "string"},
            },
            "required": ["id", "direction"],
        }
        bbox_schema = {
            "type": "array",
            "items": {"type": "number"},
            "description": "[x_min, y_min, x_max, y_max] 归一化坐标",
        }
        return {
            "type": "object",
            "properties": {
                "equipment_nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "tag": {"type": "string"},
                            "equipment_type": {"type": "string"},
                            "bbox": bbox_schema,
                            "ports": {"type": "array", "items": port_schema},
                        },
                        "required": ["id"],
                    },
                },
                "boundary_nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "boundary_type": {"type": "string"},
                            "equipment_tag": {"type": "array", "items": {"type": "string"}},
                            "description": {"type": "string"},
                            "bbox": bbox_schema,
                            "ports": {"type": "array", "items": port_schema},
                        },
                        "required": ["id"],
                    },
                },
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "source_node_id": {"type": "string"},
                            "source_port_id": {"type": "string"},
                            "target_node_id": {"type": "string"},
                            "target_port_id": {"type": "string"},
                            "stream_number": {"type": "string"},
                            "stream_name": {"type": "string"},
                            "medium": {"type": "string"},
                            "condition": {"type": "object"},
                        },
                        "required": ["id", "source_node_id", "target_node_id"],
                    },
                },
            },
            "required": ["equipment_nodes", "boundary_nodes", "edges"],
        }
