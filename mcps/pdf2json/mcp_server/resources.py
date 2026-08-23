"""MCP App Resources —— 各审核工具独立的 UI 资源。

每个审核工具对应 mcp_apps_ui/<scope>-ui/dist/index.html（Vite 单文件构建的自包含 SPA），
由 ``_get_ui_html(tool_name, scope)`` 按 scope 读取对应独立项目的构建产物。
每个工具通过 ``_meta.ui.resourceUri`` 绑定各自的稳定 URI。

本模块只定义资源常量与 ``register_resources(mcp)``，不依赖全局 ``mcp`` 实例。
"""

from __future__ import annotations

import asyncio
from typing import Callable

from fastmcp import FastMCP

from .duck_implement import _get_ui_html

PFD_TOPOLOGY_UI_URI = "ui://pfd-topology/review.html"
PLANT_UNIT_UI_URI = "ui://plant-unit/review.html"
EQUIPMENT_ASSEMBLY_UI_URI = "ui://equipment-assembly/review.html"
PROCESS_PACKAGE_UI_URI = "ui://process-package/review.html"
PFD_REFLUX_UI_URI = "ui://pfd-reflux/review.html"
COMPOSITION_TABLE_UI_URI = "ui://composition-table/review.html"
DEMO_PROGRESS_UI_URI = "ui://demo-progress/progress.html"
# step1/step2/step3 三个演示 tool 共用一个 UI 构建（scope=step），以不同 URI 区分，避免前端按
# skill::server::resourceUri 去重时被合并成单个 tool tab。
STEP1_UI_URI = "ui://step1/progress.html"
STEP2_UI_URI = "ui://step2/progress.html"
STEP3_UI_URI = "ui://step3/progress.html"

UI_MIME = "text/html;profile=mcp-app"
# 自包含 HTML（Vite 单文件构建，无外部 src/href），CSP 声明为空 allowlist。
_UI_META = {
    "ui": {"csp": {"connectDomains": [], "resourceDomains": []}}
}

# (uri, name, description, tool_name, scope) —— 6 个 resource 函数体相同，
# 仅返回 _get_ui_html(tool_name, scope)，用循环注册避免重复。
_UI_RESOURCES: list[tuple[str, str, str, str, str]] = [
    (PFD_TOPOLOGY_UI_URI, "pfd-topology-review-ui", "PFD 图纸拓扑提取的审核 UI（设备节点/边界/拓扑可视化）", "pfd_topology", "pfd-topology"),
    (PLANT_UNIT_UI_URI, "plant-unit-review-ui", "全厂装置拓扑提取的审核 UI（装置节点/物料边/拓扑可视化）", "plant_unit_topology", "plant-unit"),
    (EQUIPMENT_ASSEMBLY_UI_URI, "equipment-assembly-review-ui", "设备装配图提取的审核 UI（塔/反应器参数表单+接管列表）", "equipment_assembly", "equipment-assembly"),
    (PROCESS_PACKAGE_UI_URI, "process-package-review-ui", "工艺包章节提取的审核 UI（匹配章节表+工序说明/反应方程式编辑）", "process_package", "process-package"),
    (PFD_REFLUX_UI_URI, "pfd-reflux-review-ui", "PFD 回流结构审核 UI（塔/反应器回流判断+冷凝器/再沸器+操作条件）", "pfd_reflux", "pfd-reflux"),
    (COMPOSITION_TABLE_UI_URI, "composition-table-review-ui", "组分表提取审核 UI（组分列表+物流组成+流量/温度/压力）", "composition_table", "composition-table"),
    (DEMO_PROGRESS_UI_URI, "demo-progress-ui", "demo_progress 进度展示 UI（接收 notifications/progress 实时渲染进度条）", "demo_progress", "demo-progress"),
    # step1/step2/step3 共用一个 shared step-ui（scope=step，读同一份 dist/index.html），
    # 仅 tool_name（注入 __MCP_TOOL_NAME__）不同，用以在 UI 内区分当前步骤。
    (STEP1_UI_URI, "step1-ui", "step1 步骤演示 UI（带进度通知）", "step1", "step"),
    (STEP2_UI_URI, "step2-ui", "step2 步骤演示 UI（带进度通知）", "step2", "step"),
    (STEP3_UI_URI, "step3-ui", "step3 步骤演示 UI（带进度通知）", "step3", "step"),
]


def register_resources(mcp: FastMCP) -> None:
    """注册各审核工具的独立 UI 资源（apps-ui/<scope>-ui/dist/index.html）。

    每个 resource 读取对应的独立项目构建产物并注入 tool_name，使前端在
    host 未发送 tool-input 时仍能正确路由。tool_name / scope 通过闭包工厂
    绑定，不暴露为函数参数（否则 FastMCP 会把 URI 当作模板解析）。
    """
    for _uri, _name, _desc, _tool_name, _scope in _UI_RESOURCES:
        def _make_ui(tn: str, sc: str) -> Callable[[], str]:
            async def _ui() -> str:
                return await asyncio.to_thread(_get_ui_html, tn, sc)
            return _ui
        _ui = _make_ui(_tool_name, _scope)
        _ui.__name__ = _name.replace("-", "_")
        mcp.resource(_uri, name=_name, description=_desc, mime_type=UI_MIME, meta=_UI_META)(_ui)
