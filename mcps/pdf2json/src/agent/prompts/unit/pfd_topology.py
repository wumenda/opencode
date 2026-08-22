"""带上下文的 topology prompt：上游已提取节点，VLM 仅基于既定节点提取流股拓扑边。

与 topology.py 的区别：
    - 本文件 expert_type = "pfd_topology"，要求上游已提取设备节点与
      边界节点，并通过 context_info 注入到提示词中。
    - VLM 的任务范围仅限于：识别节点之间的边（equipment_nodes / boundary_nodes
      与上游传入完全一致，由工作流从上游直接合并，VLM 无需回传）。
    - 节点 id / tag / equipment_tag / 端口 id 必须复用上下文，禁止编造。
"""

from typing import Any

from ..core.base import PromptBuilder
from ..core.context import PromptContext
from ..core.registry import register_prompt


@register_prompt("pfd_topology", "v1")
class PFDTopologyPromptBuilderV1(PromptBuilder):
    expert_type = "pfd_topology"
    version = "v1"
    description = "无端口（节点上下文已注入）"

    _ROLE = """
        你是 PFD 拓扑提取专家。你的任务是分析化工 PFD（工艺流程图）图纸，基于上游提供的节点清单提取拓扑关系。
        拓扑关系是一个有向图，由节点和边组成：
        - 节点包括设备节点（泵、换热器、反应器、塔、容器等）和边界节点（界区进料、界区出料、跨图进料、跨图出料）
        - 节点已由上游专家从图纸上识别，**必须**复用上下文清单中的节点信息，禁止编造
        - 边表示节点之间的流股连接，从 source_node_id 指向 target_node_id，方向由箭头决定
        - 边上携带流股属性：流股编号、物料名称、相态、温度、压力、流量等

        核心原则：
        1. 你只需输出 edges（节点之间的拓扑连接关系）；equipment_nodes / boundary_nodes 无需输出，由工作流从上游上下文直接合并。
        2. 边的 source_node_id / target_node_id 必须复用上下文清单中的节点 id，禁止编造
        3. 箭头方向决定边的方向：箭头指向 = target_node_id 方向
        4. 每条边连接同一连续管线上相邻的两个节点，禁止跨过中间节点直连
        5. 流股边必须完全符合物料流向，对于有分流点和并流点的节点，必须正确分清楚真正的源节点
        6. 特别注意回流管线、分流管线、并流管线的正确源节点，必须通过管线箭头方向和工艺常识判断真正的源节点，禁止随意假设
        """

    _EDGE_DEFINITION = """
        【边（流股连接）定义】

        边表示从一个节点到另一个节点的物料流股连接。

        边字段：
        - id: 唯一标识，格式 edge_1, edge_2, ...
        - source_node_id: 起始节点 id（物料流出方），必须来自上下文清单的节点id非port id
        - target_node_id: 目标节点 id（物料流入方），必须来自上下文清单的节点id非port id
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
            - composition: 组成（组分名->质量/摩尔分数），图中可见时填写

        边界节点方向约束：
        - boundary_in / cross_drawing_in 只能作为 source_node_id
        - boundary_out / cross_drawing_out 只能作为 target_node_id
        """

    _DECISION_FLOW = """
        【提取流程--逐条管线执行】

        前提：节点清单已由上下文提供，无需重新识别节点；只需在图上定位它们。

        步骤1：在图片上定位上下文清单中的每个节点（依据 tag、name、label 等线索）。

        步骤2：逐条管线追踪连接
          - 找到每条可见的工艺实线（粗黑实线或带箭头实线）
          - 确定箭头方向：箭头指向 = target_node_id 方向
          - 沿管线追踪到相邻节点，确定 source_node_id 和 target_node_id（均来自上下文清单）
          - 读取管线旁的流股编号、物料属性等信息

        步骤3：填写边属性
          - stream_number: 管线旁标注的数字编号
          - condition: 管线旁标注的温度、压力、流量等数值
          - phase: 根据管线旁相态标注或工艺常识判断
          - 图中不可见的信息留空或填默认值
        """

    _HARD_CONSTRAINTS = """
        【硬约束--违反任一条则输出无效】

        1. 箭头方向为最高优先级证据，禁止输出与可见箭头方向相反的边。
        2. 每条边的 source_node_id 和 target_node_id 必须严格来自上下文节点清单，禁止编造或新增节点。
        3. 仅输出 edges；equipment_nodes / boundary_nodes 无需输出（由工作流从上游上下文直接合并）。
        4. 每条边连接同一连续管线上相邻的两个节点，禁止跨过中间节点直连远端。
        5. boundary_in / cross_drawing_in 只能作为 source_node_id；boundary_out / cross_drawing_out 只能作为 target_node_id。
        6. 视觉交叉不等于连通，没有连续实线证据时不输出边。
        7. phase 只能使用规定的英文枚举值，禁止使用中文。
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

    _CONTEXT_TEMPLATE = """
        【上游上下文 - 已识别节点】
        下面是上游专家已从图纸上识别出的**全部**设备节点和边界节点，是构建拓扑边的唯一合法端点集合。
        请把它们当作"权威节点清单"使用：你只能在这些节点之间建立边，不允许引入清单之外的任何节点。

        {context_info}
        """

    _CONTEXT_USAGE = """
        【上下文使用原则】
        1. 上下文中的设备节点（含 id/name/tag/equipment_type）和边界节点（含 id/boundary_type/equipment_tag/description）是图上真实存在的节点，由工作流直接合并到最终输出，你无需回传。
        2. 边的 source_node_id / target_node_id 必须复用上下文中提供的节点 id（如 equip_1、bn_1 等），保持与上游一致。
        3. 设备节点的 tag 必须复用上下文中提供的 tag 值，保持格式完全一致（如上下文为"V-101"则输出"V-101"，不可改为"V101"）。
        4. 跨图边界节点（cross_drawing_in/cross_drawing_out）的 equipment_tag 必须复用上下文中提供的 equipment_tag 列表。
        5. 你仅需自行判断节点之间的拓扑连接关系（边），上下文不提供连接信息。
        """

    _MISS_CHECK = """
        【漏连检查】
        输出前做以下检查：
        1. 所有边的 source_node_id / target_node_id 是否都在上下文节点清单中（无任何编造）。
        2. 每个设备节点是否至少有一条入边或出边（孤立设备通常不正常）。
        3. 每个 boundary_in / cross_drawing_in 是否作为 source_node_id 出现在至少一条边中。
        4. 每个 boundary_out / cross_drawing_out 是否作为 target_node_id 出现在至少一条边中。
        5. 是否有可见管线被遗漏（特别是分支管线）。
        6. 箭头方向是否与边的 source_node_id/target_node_id 一致。
        7. 边界节点的方向约束是否满足。
        """

    _OUTPUT_FORMAT = """
        【输出要求】
        直接输出纯 JSON，禁止 markdown，禁止解释文字。
        {{
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

        context_info = context.extra.get("context_info", "")
        if not context_info:
            raise ValueError(
                "PFDTopologyPromptBuilder requires non-empty 'context_info' in "
                "PromptContext.extra; upstream nodes must be provided."
            )
        sections.append(self._CONTEXT_TEMPLATE.format(context_info=context_info))
        sections.append(self._CONTEXT_USAGE)

        sections.extend(
            [
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
        return {
            "type": "object",
            "properties": {
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
            "required": ["edges"],
        }


@register_prompt("pfd_topology", "v2")
class PFDTopologyPromptBuilderV2(PromptBuilder):
    expert_type = "pfd_topology"
    version = "v2"
    description = "带端口（节点+端口上下文已注入）"

    _ROLE = """
        你是 PFD 拓扑提取专家。你的任务是分析化工 PFD（工艺流程图）图纸，基于上游提供的节点+端口清单提取拓扑关系。
        拓扑关系是一个有向图，由节点和边组成：
        - 节点包括设备节点和边界节点，每个节点带若干端口；节点和端口均由上下文提供，**必须**复用
        - 边表示节点之间的流股连接，从 source_node_id 节点的某个端口指向 target_node_id 节点的某个端口
        - 边上携带流股属性：流股编号、物料名称、相态、温度、压力、流量等

        核心原则：
        1. 你只需输出 edges；equipment_nodes / boundary_nodes（含 ports）无需输出，由工作流从上游上下文直接合并。
        2. 边的 source_node_id / target_node_id 与 source_port_id / target_port_id 必须复用上下文清单中的节点 id 与端口 id，禁止编造
        3. 箭头方向决定边的方向：箭头指向 = target_node_id 方向
        4. 每条边连接同一连续管线上相邻的两个节点，禁止跨过中间节点直连
        5. 边的 source_port_id / target_port_id 必须引用上下文中提供的端口 id
        6. 流股边必须完全符合物料流向，对于有分流点和并流点的节点，必须正确分清楚真正的源节点
        7. 特别注意回流管线、分流管线、并流管线的正确源节点，必须通过管线箭头方向和工艺常识判断真正的源节点，禁止随意假设
        """

    _EDGE_DEFINITION = """
        【边（流股连接）定义】

        边表示从一个节点的某个端口到另一个节点的某个端口的物料流股连接。

        边字段：
        - id: 唯一标识，格式 edge_1, edge_2, ...
        - source_node_id: 起始节点 id（物料流出方），必须来自上下文清单
        - source_port_id: 起始节点的端口 id（物料从该端口流出），必须引用 source_node_id 节点上 direction 为 "output" 或 "unknown" 的端口
        - target_node_id: 目标节点 id（物料流入方），必须来自上下文清单
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
            - composition: 组成（组分名->质量/摩尔分数），图中可见时填写

        端口引用约束：
        - source_port_id 必须属于 source_node_id 节点的 ports 列表；target_port_id 必须属于 target_node_id 节点的 ports 列表
        - 若无法确定具体端口，source_port_id / target_port_id 可留空字符串 ""，但优先尝试匹配
        - 同一 source_port_id 可出现在多条边中（表示分流），同一 target_port_id 可出现在多条边中（表示并流）
        """

    _DECISION_FLOW = """
        【提取流程--逐条管线执行】

        前提：节点+端口清单由上下文给定，无需识别节点和端口，直接定位即可。

        步骤1：在图片上定位上下文清单中的每个节点与端口。

        步骤2：逐条管线追踪连接
          - 找到每条可见的工艺实线（粗黑实线或带箭头实线）
          - 确定箭头方向：箭头指向 = target_node_id 方向
          - 沿管线追踪到相邻节点，确定 source_node_id 和 target_node_id
          - 确定该管线在 source_node_id 节点上的端口 id（source_port_id）和在 target_node_id 节点上的端口 id（target_port_id）
          - 读取管线旁的流股编号、物料属性等信息

        步骤3：填写边属性
          - stream_number: 管线旁标注的数字编号
          - condition: 管线旁标注的温度、压力、流量等数值
          - phase: 根据管线旁相态标注或工艺常识判断
          - 图中不可见的信息留空或填默认值
        """

    _HARD_CONSTRAINTS = """
        【硬约束--违反任一条则输出无效】

        1. 箭头方向为最高优先级证据，禁止输出与可见箭头方向相反的边。
        2. 每条边的 source_node_id 和 target_node_id 必须严格来自上下文节点清单，禁止编造或新增节点。
        3. 仅输出 edges；equipment_nodes / boundary_nodes（含 ports）无需输出（由工作流从上游上下文直接合并）。
        4. 每条边连接同一连续管线上相邻的两个节点，禁止跨过中间节点直连远端。
        5. boundary_in / cross_drawing_in 只能作为源节点；boundary_out / cross_drawing_out 只能作为目标节点。
        6. 视觉交叉不等于连通，没有连续实线证据时不输出边。
        7. phase 只能使用规定的英文枚举值，禁止使用中文。
        8. 不提取任何坐标/位置信息（bbox、position、port.position 等）。
        9. source_port_id 必须属于 source_node_id 节点的 ports 列表；target_port_id 必须属于 target_node_id 节点的 ports 列表（或留空字符串）。
        10. 边引用的端口 id 必须复用上下文提供的端口 id，不得改写。
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

    _CONTEXT_TEMPLATE = """
        【上游上下文 - 已识别节点（含端口）】
        下面是上游专家已从图纸上识别出的**全部**设备节点、边界节点及其端口，是构建拓扑边的唯一合法端点集合。
        请把它们当作"权威节点/端口清单"使用：你只能在这些节点/端口之间建立边，不允许引入清单之外的任何节点或端口。

        {context_info}
        """

    _CONTEXT_USAGE = """
        【上下文使用原则】
        1. 上下文中的设备节点（含 id/name/tag/equipment_type/ports）和边界节点（含 id/boundary_type/equipment_tag/description/ports）是图上真实存在的节点，由工作流直接合并到最终输出，你无需回传。
        2. 边的 source_node_id / target_node_id 必须复用上下文中提供的节点 id，保持与上游一致。
        3. 设备节点的 tag 必须复用上下文中提供的 tag 值，保持格式完全一致（如上下文为"V-101"则输出"V-101"，不可改为"V101"）。
        4. 跨图边界节点（cross_drawing_in/cross_drawing_out）的 equipment_tag 必须复用上下文中提供的 equipment_tag 列表。
        5. 边引用的端口 id 必须复用上下文中提供的端口 id（id/direction/category/label/orientation/channel 与上游一致）。
        6. 你仅需自行判断节点之间的拓扑连接关系（边），上下文不提供连接信息。
        """

    _MISS_CHECK = """
        【漏连检查】
        输出前做以下检查：
        1. 所有边的 source_node_id / target_node_id 是否都在上下文节点清单中（无任何编造）。
        2. 每个设备节点是否至少有一条入边或出边（孤立设备通常不正常）。
        3. 每个 boundary_in / cross_drawing_in 是否作为 source_node_id 出现在至少一条边中。
        4. 每个 boundary_out / cross_drawing_out 是否作为 target_node_id 出现在至少一条边中。
        5. 是否有可见管线被遗漏（特别是分支管线）。
        6. 箭头方向是否与边的 source_node_id/target_node_id 一致。
        7. 边界节点的方向约束是否满足。
        8. 每条边的 source_port_id 是否属于 source_node_id 节点的 ports 列表（或为空字符串）。
        9. 每条边的 target_port_id 是否属于 target_node_id 节点的 ports 列表（或为空字符串）。
        """

    _OUTPUT_FORMAT = """
        【输出要求】
        直接输出纯 JSON，禁止 markdown，禁止解释文字。
        {{
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
            }}
          ]
        }}"""

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]

        if context.has_process_description:
            sections.append(self.build_process_description_section(context.process_description))

        context_info = context.extra.get("context_info", "")
        if not context_info:
            raise ValueError(
                "PFDTopologyPromptBuilder requires non-empty 'context_info' in "
                "PromptContext.extra; upstream nodes (with ports) must be provided."
            )
        sections.append(self._CONTEXT_TEMPLATE.format(context_info=context_info))
        sections.append(self._CONTEXT_USAGE)

        sections.extend(
            [
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
        return {
            "type": "object",
            "properties": {
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
            "required": ["edges"],
        }


@register_prompt("pfd_topology", "v3")
class PFDTopologyPromptBuilderV3(PromptBuilder):
    expert_type = "pfd_topology"
    version = "v3"
    description = "角色+目标"

    _ROLE = """
        你是 PFD 拓扑提取专家。你的任务是分析化工 PFD（工艺流程图）图纸，基于上游提供的节点+端口清单提取拓扑关系。
        拓扑关系是一个有向图，由节点和边组成：
        - 节点包括设备节点和边界节点，每个节点带若干端口；节点和端口均由上下文提供，**必须**复用
        - 边表示节点之间的流股连接，从 source_node_id 节点的某个端口指向 target_node_id 节点的某个端口
        - 边上携带流股属性：流股编号、物料名称、相态、温度、压力、流量等

        核心原则：
        1. 你只需输出 edges；equipment_nodes / boundary_nodes（含 ports）无需输出，由工作流从上游上下文直接合并。
        2. 边的 source_node_id / target_node_id 与 source_port_id / target_port_id 必须复用上下文清单中的节点 id 与端口 id，禁止编造
        3. 箭头方向决定边的方向：箭头指向 = target_node_id 方向
        4. 每条边连接同一连续管线上相邻的两个节点，禁止跨过中间节点直连
        5. 边的 source_port_id / target_port_id 必须引用上下文中提供的端口 id
        6. 流股边必须完全符合物料流向，对于有分流点和并流点的节点，必须正确分清楚真正的源节点
        """

    _EDGE_DEFINITION = """
        【边（流股连接）定义】

        边表示从一个节点的某个端口到另一个节点的某个端口的物料流股连接。

        边字段：
        - id: 唯一标识，格式 edge_1, edge_2, ...
        - source_node_id: 起始节点 id（物料流出方），必须来自上下文清单
        - source_port_id: 起始节点的端口 id（物料从该端口流出），必须引用 source_node_id 节点上 direction 为 "output" 或 "unknown" 的端口
        - target_node_id: 目标节点 id（物料流入方），必须来自上下文清单
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
            - composition: 组成（组分名->质量/摩尔分数），图中可见时填写

        端口引用约束：
        - source_port_id 必须属于 source_node_id 节点的 ports 列表；target_port_id 必须属于 target_node_id 节点的 ports 列表
        - 若无法确定具体端口，source_port_id / target_port_id 可留空字符串 ""，但优先尝试匹配
        - 同一 source_port_id 可出现在多条边中（表示分流），同一 target_port_id 可出现在多条边中（表示并流）
        """


    _CONTEXT_TEMPLATE = """
        【上游上下文 - 已识别节点（含端口）】
        下面是上游专家已从图纸上识别出的**全部**设备节点、边界节点及其端口，是构建拓扑边的唯一合法端点集合。
        请把它们当作"权威节点/端口清单"使用：你只能在这些节点/端口之间建立边，不允许引入清单之外的任何节点或端口。

        {context_info}
        """

    _CONTEXT_USAGE = """
        【上下文使用原则】
        1. 上下文中的设备节点（含 id/name/tag/equipment_type/ports）和边界节点（含 id/boundary_type/equipment_tag/description/ports）是图上真实存在的节点，由工作流直接合并到最终输出，你无需回传。
        2. 边的 source_node_id / target_node_id 必须复用上下文中提供的节点 id，保持与上游一致。
        3. 设备节点的 tag 必须复用上下文中提供的 tag 值，保持格式完全一致（如上下文为"V-101"则输出"V-101"，不可改为"V101"）。
        4. 跨图边界节点（cross_drawing_in/cross_drawing_out）的 equipment_tag 必须复用上下文中提供的 equipment_tag 列表。
        5. 边引用的端口 id 必须复用上下文中提供的端口 id（id/direction/category/label/orientation/channel 与上游一致）。
        6. 你仅需自行判断节点之间的拓扑连接关系（边），上下文不提供连接信息。
        """

    _OUTPUT_FORMAT = """
        【输出要求】
        直接输出纯 JSON，禁止 markdown，禁止解释文字。
        {{
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
            }}
          ]
        }}"""

    def build(self, context: PromptContext) -> str:
        sections = [self._ROLE]

        if context.has_process_description:
            sections.append(self.build_process_description_section(context.process_description))

        context_info = context.extra.get("context_info", "")
        if not context_info:
            raise ValueError(
                "PFDTopologyPromptBuilder requires non-empty 'context_info' in "
                "PromptContext.extra; upstream nodes (with ports) must be provided."
            )
        sections.append(self._CONTEXT_TEMPLATE.format(context_info=context_info))
        sections.append(self._CONTEXT_USAGE)

        sections.extend(
            [
                self._EDGE_DEFINITION,
                self._OUTPUT_FORMAT,
            ]
        )

        return "\n".join(s for s in sections if s)

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
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
            "required": ["edges"],
        }
