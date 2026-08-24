"""FastMCP HTTP 服务器入口 —— 组装 tools / resources 并启动。

本模块只负责：
- 创建 ``FastMCP`` 实例
- 注册 ``tools.register_tools`` 与 ``resources.register_resources``
- 提供 HTTP 启动入口 ``main``

工具与资源定义已拆分到 ``tools`` / ``resources`` 模块；本模块对其
re-export（常量、工具函数、``mcp``、``main``），以保持既有
``from mcp_server.server import mcp`` / ``from mcp_server import server`` 兼容。

启动（HTTP 模式）::

    python -m mcp_server
    # 或自定义 host/port
    MCP_HOST=0.0.0.0 MCP_PORT=9000 python -m mcp_server
"""

from __future__ import annotations

import os

from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from src.core import get_logger, setup_logging

from .duck_implement import HostClient

# ---------------------------------------------------------------------------
# HostClient 全局单例（AGENT.md 要求：全进程共享，禁止 tools.py 就地构造）
# 定义在 tools 导入之前，避免 tools.py 反向导入时产生循环依赖。
#
# 使用 HostClient：PDF 经 get_file 从 opencode host 工作区读取、最终 JSON 经
# save_file 写回工作区；渲染出的中间图片落到本地供上游读取（豁免 #5）。
# host 地址 / 凭据 / 工作区从环境变量读取：
#   - OPENCODE_HOST_URL         host 基址（默认 http://127.0.0.1:4097）
#   - OPENCODE_SERVER_USERNAME  Basic Auth 用户名（默认 opencode）
#   - OPENCODE_SERVER_PASSWORD  host 口令（与 opencode serve 一致）
#   - OPENCODE_WORKSPACE        工作区绝对路径（作为 location[directory]）
# ---------------------------------------------------------------------------
_host_url = os.getenv("OPENCODE_HOST_URL", os.getenv("FILE_SERVICE_URL", "http://127.0.0.1:4097"))
_host_username = os.getenv("OPENCODE_SERVER_USERNAME", "opencode")
_host_password = os.getenv("OPENCODE_SERVER_PASSWORD", "")
_host_workspace = os.getenv("OPENCODE_WORKSPACE", "D:\\项目\\AI-For-Redesign\\代码库\\mock_file_server\\file_storage")
_host_client_singleton = HostClient(
    base_url=_host_url,
    username=_host_username,
    password=_host_password,
    workspace=_host_workspace,
)


def get_host_client() -> HostClient:
    """返回全进程共享的 HostClient 单例。"""
    return _host_client_singleton


from .resources import (
    COMPOSITION_TABLE_UI_URI,
    EQUIPMENT_ASSEMBLY_UI_URI,
    PFD_REFLUX_UI_URI,
    PFD_TOPOLOGY_UI_URI,
    PLANT_UNIT_UI_URI,
    PROCESS_PACKAGE_UI_URI,
    UI_MIME,
    register_resources,
)
from .tools import (
    composition_table,
    demo_progress,
    equipment_assembly,
    pfd_reflux,
    pfd_topology,
    plant_unit_topology,
    process_package,
    read_image,
    register_tools,
    step1,
    step2,
    step3,
    submit_review,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# FastMCP 实例
# ---------------------------------------------------------------------------
mcp: FastMCP = FastMCP(
    "pfd-workflow-server",
    instructions=(
        "PFD 图纸分析工作流 MCP 服务器，提供 6 个能力："
        "pfd_topology（PFD 拓扑提取）、process_package（工艺包章节提取）、"
        "plant_unit_topology（全厂装置拓扑）、equipment_assembly（设备装配图提取）、"
        "pfd_reflux（PFD 塔与反应器回流结构分析）、"
        "composition_table（组分表提取）。"
    ),
)

# 注册资源与工具（依赖 mcp 实例，故放在实例创建之后）
register_resources(mcp)
register_tools(mcp)


# ---------------------------------------------------------------------------
# HTTP 启动入口
# ---------------------------------------------------------------------------
def main() -> None:
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8008"))
    cors_origins = os.getenv("MCP_CORS_ORIGINS", "*").split(",")
    if cors_origins == ["*"] and host == "0.0.0.0":
        logger.warning(
            "CORS allow_origins=['*'] with host=0.0.0.0 exposes the MCP server "
            "to any origin; set MCP_CORS_ORIGINS to restrict access (e.g. "
            "'http://localhost:5173,http://127.0.0.1:5173')"
        )
    cors_middleware = Middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    logger.info("Starting MCP server (HTTP) at http://%s:%s/mcp", host, port)
    mcp.run(
        transport="http",
        host=host,
        port=port,
        host_origin_protection=False,
        middleware=[cors_middleware],
        # 禁用 uvicorn 自带的 LOGGING_CONFIG，使其 access/error 日志传播到
        # root logger，统一使用 setup_logging 配置的东八区时间格式。
        uvicorn_config={"log_config": None},
    )


if __name__ == "__main__":
    setup_logging()
    main()
