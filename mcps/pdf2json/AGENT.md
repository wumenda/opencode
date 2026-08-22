# AGENT.md

> 发布前立场：基础正确优先于兼容性（当前仓库还未发布）

本文件向模型说明本项目的业务。项目是一个化工 PFD（工艺流程图）图纸解析系统，基于多专家（Multi-Expert）VLM 架构，将 PDF 图纸转化为结构化 JSON，供下游工艺建模与技改方案生成消费。

业务按粒度分为三层：**全厂级 → 装置级 → 设备级**，每层有独立的提取工作流，统一通过 `task_type` 调度（入口：`interface/common/workflow_adapter.py`）。

---

## 一、全厂级物料流程拓扑提取

提取整厂各装置之间的物料流向拓扑。调用端输入全厂流程图 PDF，渲染为图片后传入工作流（多页由调用端逐页处理，见[输入边界](#输入边界pdf-与图片的职责划分)）。

**两种图纸类型**（由模型自动判别后选择对应提示词提取）：

| 类型 | 标识 | 特征 | 拓扑来源 |
|---|---|---|---|
| 常规类型 | `plant_unit_general` | 图上有管线连接各装置 | VLM 提取（逐单元 `one_by_one` 或整图 `all_in_one`） |
| 密集类型 | `plant_unit_dense` | 以物料信息表呈现，无管线 | 物料名匹配算法（无 VLM） |

**提取流程**（`PlantUnitTopologyWorkflow`，`src/agent/workflow/plant/topology.py`）：

1. **Phase 0 图纸类型判别**：`PlantUnitDrawingTypeExpert` 判断 `general` / `dense` / `unknown`（unknown 抛错要求重传）
2. **Phase 1 装置节点提取**：`PlantUnitExpert` 按判别类型选择提示词，提取装置节点（含 feeds / products）
3. **Phase 2 拓扑提取**（按类型分支）：
   - general：VLM 提取拓扑边 → 校验移除幻觉边 → 物料名匹配回补缺失边
   - dense：`infer_topology_by_material_matching` 物料名匹配算法直接推理拓扑
4. **Phase 3 合并**：节点 + 拓扑合并为 `PlantUnitDrawing`

任务类型：`plant_unit_topology`

---

## 二、装置级设备间拓扑关系提取

提取单个装置内设备之间的流股拓扑。调用端输入装置级 PFD PDF，逐页渲染为图片后传入工作流；多页提取逻辑（逐页调用、结果聚合成数组）由调用端负责，工作流只处理单张图片。

### 主流程：四步提取

`PFDTopologyWorkflow`（`src/agent/workflow/unit/pfd_topology.py`）编排四个专家：

1. **drawing_info**（图签信息）：`DrawingInfoExpert` 提取图签元数据
2. **equipment**（设备节点）：`EquipmentExpert` 提取设备节点（含位号、bbox、端口）
3. **boundary_node**（边界节点）：`BoundaryNodeExpert` 提取边界节点（进料/出料）
4. **topology**（流股拓扑）：`PFDTopologyExpert` 以前三步输出为上下文，提取流股边

> Phase 1 的 drawing_info / equipment / boundary_node 三步并行，Phase 2 的 topology 依赖前三步注入的节点上下文，Phase 3 将上游节点（含 bbox）与 VLM 提取的边合并。工作流处理单张图片；多页 PDF 由调用端逐页调用后聚合，跨页拼接若需要由调用端负责。

任务类型：`pfd_topology`

### 附加能力 1：工艺说明书信息提取

从输入的工艺说明书 PDF 中按章节定位并提取结构化信息（工序说明、反应方程式等）。

- 工作流：`ProcessPackageWorkflow`（`src/agent/workflow/unit/process_package.py`）
- 流程：`PdfSectionExtractor`（书签优先 + 正则回退）章节抽取 → `ProcessPackageExpert` 输出结构化结果
- 任务类型：`process_package`

### 附加能力 2：主流程设备拓扑连接信息提取

从输入的工艺说明书（和工艺设备表）中提取主流程设备之间的拓扑连接关系。纯文本通道，调用 text-only API。

- 专家：`ProcessDescriptionTopologyExpert`（`src/agent/experts/unit/process_description_topology.py`）
- 输出：设备节点列表（id / name / tag）+ 物料连接关系列表（source / target / material_name）
- 提取规则：按位号前缀（V/T/R/E/P/FL/M）识别设备；按物料流向描述（"A 进入 B""A 送入 B"等）提取连接；界外物料用 `external` 表示；仅提取文档明确描述的连接，不靠常识推断。

### 附加能力 3：PFD 塔与反应器回流结构分析

从 PFD 图纸图片中识别所有塔与反应器，判断是否存在回流结构，并提取塔回流详情与设备操作条件。

- 工作流：`PFDRefluxWorkflow`（`src/agent/workflow/unit/pfd_reflux.py`）
- 流程：`PFDRefluxExpert` 识别塔/反应器 → 判断回流结构（塔顶回流/塔釜回流/反应器循环） → 塔回流详情（塔顶冷凝器、塔釜再沸器、回流量） → 设备操作条件（塔顶/塔釜温度压力、反应器温度压力）
- 输入：PFD 图纸图片（单张，PDF 由调用端逐页渲染）
- 任务类型：`pfd_reflux`

---

## 三、设备级装配图信息提取

从传入的设备装配图图片上提取装配信息（PDF 由调用端渲染为图片）。第一步由模型判断装配图类型，再路由到对应专家提取。

**支持的设备类型**：

| 类型 | 标识 | 提取专家 |
|---|---|---|
| 板式塔 | `column_tray` | `ColumnAssemblyExpert`（按类型选择提示词） |
| 填料塔 | `column_packed` | `ColumnAssemblyExpert`（按类型选择提示词） |
| 反应器 | `reactor` | `ReactorAssemblyExpert` |

**提取流程**（`EquipmentAssemblyWorkflow`，`src/agent/workflow/equipment/equipment_assembly.py`）：

1. **Phase 1 类型判别**：`EquipmentTypeExpert` 判断 `column_tray` / `column_packed` / `reactor` / `unknown`
2. **Phase 2 装配信息提取**（按类型路由）：
   - column_tray / column_packed → `ColumnAssemblyExpert` 输出 `{"distillation_column": {...}}`
   - reactor → `ReactorAssemblyExpert` 输出 `{"reactor_design": {...}}`
   - unknown → 默认走 `ColumnAssemblyExpert`（带告警）

任务类型：`equipment_assembly`

---

## 任务类型总览

| task_type | 业务模块 | 粒度 | 工作流输入 | 多页处理 |
|---|---|---|---|---|
| `plant_unit_topology` | 全厂物料流程拓扑 | 全厂级 | 图片 | 调用端逐页 |
| `pfd_topology` | 设备间流股拓扑 | 装置级 | 图片 | 调用端逐页 |
| `composition_table` | 组分表信息提取 | 装置级 | 图片 | 调用端逐页转图 + 调用 `aggregate` 聚合 |
| `process_package` | 工艺说明书信息提取 | 装置级 | PDF（工作流内部抽章节） | 工作流内部 |
| `pfd_reflux` | 塔与反应器回流结构分析 | 装置级 | 图片 | 调用端逐页 |
| `equipment_assembly` | 装配图信息提取 | 设备级 | 图片 | 调用端逐页 |

三种接入方式：CLI（`PDF-TOOL`）、HTTP API（`PDF-REVIEW`）、MCP 服务（`PDF-TOOL-MCP`），均通过 `WorkflowAdapter.run_session` 按 `task_type` 统一调度。

---

## 输入边界：PDF 与图片的职责划分

项目对 PDF 与图片的职责划分有严格约定，调用端与工作流各司其职：

| 层 | 输入 | 职责 |
|---|---|---|
| **调用端**（`entry/` 脚本、`mcp_server/`） | PDF | PDF -> 图片渲染、**多页提取逻辑**（页范围切分、逐页/并行调用工作流、结果聚合） |
| **工作流**（`src/agent/workflow/`） | 图片（PNG） | 单张图片的结构化信息提取，**不感知 PDF 与页码** |

要点：

- 图像类工作流的 `analyze()` 方法只接收**单张图片路径**（`image_path: str`），不接收 PDF，也不处理多页转图。
- 调用端负责把 PDF 渲染为图片（`entry/_common.py: pdf_to_images_range` / `src/_internal/pdf_utils.py: pdf_to_images`），按页范围逐页调用工作流，再将每页结果聚合成数组输出。
- 多页跨页合并（如设备去重、流股拼接）若需要，由调用端或上层逻辑负责，工作流本身不做跨页聚合。例外：`CompositionTableWorkflow` 提供独立的 `aggregate()` 静态方法做组分表跨页聚合（components 去重 + streams 汇总），但其 `analyze()` 仍只处理单张图片，由调用端逐页调用 `analyze` 后再调用 `aggregate`。
- 例外：`ProcessPackageWorkflow`（工艺说明书信息提取）走纯文本通道，调用端直接传 `pdf_path`，由工作流内部 `PdfSectionExtractor` 抽取章节文本，不经过图片。

---

## 包能力出口：`src/agent/workflow`

`src/agent/workflow` 是 `src` 包全部业务能力的**唯一对外出口**。其 [__init__.py](file:///d:/项目/AI-For-Redesign/代码库/workspace/PDF2JSON - 副本/src/agent/workflow/__init__.py) 统一 re-export 工作流基类、注册表与各业务工作流。任何外部接入层都应从 `src.agent.workflow` 导入，**不应**深入 `src/agent/experts/`、`src/agent/workflow/unit|plant|equipment/` 等内部子模块——后者为实现细节，接口随业务演进可能调整。

公开 API：

| 类别 | 导出项 | 说明 |
|---|---|---|
| 基类 | `BaseWorkflow` | 通用工作流基类（配置存储 + 专家初始化钩子） |
| 注册表 | `WorkflowRegistry` / `get_default_registry` / `get_workflow_info` / `list_workflows` | 按 `task_type` 注册与查询工作流（`WorkflowInfo` 含 `module_path` / `class_name`） |
| 全厂级 | `PlantUnitTopologyWorkflow` | 整厂装置物料拓扑提取 |
| 装置级 | `PFDTopologyWorkflow` / `ProcessPackageWorkflow` | 设备间流股拓扑 / 工艺说明书信息提取 |
| 设备级 | `EquipmentAssemblyWorkflow` | 装配图信息提取 |

**构建外部接入（如 MCP server）时**，从 `src.agent.workflow` 导入即可，例如：

```python
from src.agent.workflow import (
    get_default_registry,
    get_workflow_info,
    PlantUnitTopologyWorkflow,
    PFDTopologyWorkflow,
    ProcessPackageWorkflow,
    EquipmentAssemblyWorkflow,
)
```

> 上述三种接入方式（CLI / HTTP API / MCP 服务）均以此包为出口：通过 `get_default_registry()` 取得按 `task_type` 注册的工作流，再交由 `WorkflowAdapter.run_session` 统一调度执行。

---

## 代码规范：文件读写与 HostClient 鸭子类型

`src` 包内的所有文件读取 / 保存**必须**经由 `duck/host_client.py` 中的 `HostClient` 鸭子类型协议（占位），**禁止**在 `src` 内直接使用 `open()`、`Path.read_text()`、`Path.write_text()` 等本地文件 API 进行业务文件的读写。

### 三层职责

| 层 | 角色 | 说明 |
|---|---|---|
| `duck/host_client.py` | 鸭子类型占位 | 定义 `HostClient` Protocol（`save_file` / `get_file`），`src` 仅依赖此协议类型，不感知具体实现 |
| `src/` 内部 | 协议消费方 | 工作流 / 专家通过构造函数注入的 `host_client: Optional[HostClient]` 调用 `save_file` / `get_file`，不绑定任何具体存储 |
| 接入层（`mcp_server/`、`entry/`） | 实现注入方 | 构造真实 `HostClient` 实现并注入工作流 |

### MCP 服务接入：全局单例注入

`mcp_server/mcp_server/server.py` 是 MCP 服务的真实组装入口，负责：

1. 在模块加载时创建 `mcp_server/duck_implement` 中 `HostClient` 实现的**全局单例**（如 `LocalHostClient` 或 `MCPHostClient`），全进程共享同一个实例。
2. 将该单例传入各工作流构造（经 `tools.py` 或 `WorkflowAdapter`），完成网络请求 / 本地文件读写的落地。

```python
# mcp_server/server.py -- 全局单例注入示例
from .duck_implement import LocalHostClient

# 全局单例：全进程共享，避免每次工具调用重复构造
_host_client_singleton = LocalHostClient()

def get_host_client() -> LocalHostClient:
    return _host_client_singleton
```

要点：

- **禁止**在 `mcp_server/tools.py` 各工具函数内就地 `LocalHostClient()` 重复构造，统一从 `server.py` 的全局单例取用。
- `src` 内部只引用 `duck.host_client.HostClient` 类型，**不** import `mcp_server.duck_implement` 或 `entry._common` 的任何实现，保持依赖方向单一（接入层 -> `src`，`src` -> `duck` 协议）。
- CLI 入口（`entry/`）使用独立的 `EntryHostClient` 实现，同样以单例方式注入，规则与 MCP 服务一致。

### 豁免条款

以下场景豁免 HostClient 协议（在 `src` 内允许直接使用本地文件 API）：

1. **启动期配置读取**：`src/core/infra/config.py`、`src/core/infra/yaml_config.py` 读取打包配置文件（`providers.yaml`、`*.yaml`），仅在进程启动 `Settings.from_env()` / `Settings.from_yaml()` 路径上调用。
2. **评测代码**：`src/core/evaluation/` 下读取 label / extraction JSON 的评测脚本，非生产链路。
3. **调试日志写入**：`_save_thinking_content`、`_save_orphaned_thinking`、`_save_failed_json_text` 将调试信息写入 `logs/` 目录，非业务产物，且需在 HostClient 不可用时仍能写入。
4. **已废弃的通用 IO 工具**：`src/core/utils.py` 的 `save_json` / `load_json`、`src/core/io/annotation_io.py` 的 `load_image` 等已标注 deprecated，不应在生产代码中调用。
5. **库 API 路径消费**：`fitz.open` / `PIL.Image.open` 等必须接收文件路径的库 API，允许消费**已由 HostClient 解析为本地临时文件**的路径（经 `get_file_path` / `_resolve_input_path` / `_load_image` / `_load_pdf_bytes` 取得），数据已通过 HostClient 落地。涉及模块：`src/core/io/image_io.py`、`src/core/client/vision_client.py`、`src/agent/preprocessor/preprocessor.py`、`src/agent/experts/core/base.py`（`_resolve_image_size`）、`src/_internal/document_loader.py` / `pdf_section_extractor.py` / `region_divider.py`、`src/agent/validation/equipment_table_checker.py` 的路径回退分支。另：`fitz.open(stream=bytes, ...)`、`Image.open(io.BytesIO(...))` 属于内存流操作，不是本地文件 API，不在此限。

---

## 代码规范：日志记录

**非必要不记录 log。**

- 仅在关键节点（工作流入口/出口、专家调用前后、错误分支、跨进程通信边界）记录必要日志，用于问题定位与进度追踪。
- 禁止在循环内、热路径、正常数据流中堆砌 `logger.info` / `print` 调试性输出。
- 不写"此处已执行""返回值为 X"等无信息量的日志；不通过 log 复述变量值来代替调试器。
- 临时调试用的 `print` / `logger.debug` 在提交前必须删除。
- 错误日志应包含上下文（输入标识、阶段名、异常类型），而非空洞的 `error`。
