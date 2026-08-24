"""MCP Apps UI 模板 -- 服务端最小示例。

演示三种工具模式（每个工具绑定独立的 UI 资源）：
    1. simple_tool   -- 快速返回结果，无进度推送   -> ui://mcp-app-ui/simple/index.html
    2. progress_tool -- 逐步推送进度，返回结果      -> ui://mcp-app-ui/progress/index.html
    3. review_tool   -- 推送进度 + 阻塞等待人工审核  -> ui://mcp-app-ui/review/index.html

配套 ui 前端使用（三个独立 ui 项目，各自构建）：
    1. cd ../simple-ui/ui   && npm run build   # 生成 dist/index.html
       cd ../progress-ui/ui && npm run build   # 生成 dist/index.html
       cd ../review-ui/ui   && npm run build   # 生成 dist/index.html
    2. cd .. && python -m server_example.server   # 在 mcp-apps-ui 根目录启动 MCP Server

依赖：fastmcp>=3.4.4
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Any, Optional

from fastmcp import Context, FastMCP
from fastmcp.apps import AppConfig

logger = logging.getLogger(__name__)

mcp: FastMCP = FastMCP("mcp-app-ui-example")

# 三个独立 UI 项目的构建产物路径（各自 npm run build 生成 dist/index.html）
_UI_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-apps-ui"))
UI_HTML_PATHS: dict[str, str] = {
    "simple": os.path.join(_UI_ROOT, "simple-ui", "ui", "dist", "index.html"),
    "progress": os.path.join(_UI_ROOT, "progress-ui", "ui", "dist", "index.html"),
    "review": os.path.join(_UI_ROOT, "review-ui", "ui", "dist", "index.html"),
}


# ---------------------------------------------------------------------------
# UI 资源：返回各 ui 项目的构建产物（一个工具一个独立 ui 项目）
# ---------------------------------------------------------------------------
@mcp.resource("ui://mcp-app-ui/simple/index.html")
def get_simple_ui_html() -> str:
    """返回 simple_tool 的 UI HTML（simple-ui 项目的构建产物）。"""
    with open(UI_HTML_PATHS["simple"], "r", encoding="utf-8") as f:
        return f.read()


@mcp.resource("ui://mcp-app-ui/progress/index.html")
def get_progress_ui_html() -> str:
    """返回 progress_tool 的 UI HTML（progress-ui 项目的构建产物）。"""
    with open(UI_HTML_PATHS["progress"], "r", encoding="utf-8") as f:
        return f.read()


@mcp.resource("ui://mcp-app-ui/review/index.html")
def get_review_ui_html() -> str:
    """返回 review_tool 的 UI HTML（review-ui 项目的构建产物）。"""
    with open(UI_HTML_PATHS["review"], "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 辅助：发送携带 uiEvent 的 progress 通知
# ---------------------------------------------------------------------------
async def send_progress_with_data(
    ctx: Context,
    progress: float,
    total: Optional[float] = None,
    message: Optional[str] = None,
    ui_event: Optional[dict[str, Any]] = None,
) -> None:
    """发送携带 uiEvent 扩展字段的 progress 通知。"""
    try:
        from mcp.types import ProgressNotification, ProgressNotificationParams

        try:
            session = ctx.session
        except RuntimeError:
            session = None
        request_ctx = getattr(ctx, "request_context", None)
        meta = getattr(request_ctx, "meta", None) if request_ctx else None
        token = getattr(meta, "progressToken", None) if meta else None

        if session is not None and token is not None:
            params: dict[str, Any] = {"progressToken": token, "progress": progress}
            if total is not None:
                params["total"] = total
            if message is not None:
                params["message"] = message
            if ui_event is not None:
                params["uiEvent"] = ui_event
            await session.send_notification(
                ProgressNotification(
                    method="notifications/progress",
                    params=ProgressNotificationParams(**params),
                )
            )
            return
    except Exception as e:
        logger.debug("send_progress_with_data failed, fallback: %s", e)
    await ctx.report_progress(progress, total, message)


# ---------------------------------------------------------------------------
# 审核阻塞基础设施
# ---------------------------------------------------------------------------
_review_events: dict[str, asyncio.Event] = {}
_review_results: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Tool 1: simple_tool -- 快速返回结果（无进度）
# ---------------------------------------------------------------------------
@mcp.tool(app=AppConfig(resource_uri="ui://mcp-app-ui/simple/index.html"))
def simple_tool(input_path: str = None) -> dict[str, Any]:
    """简单工具：直接返回结果，无进度推送。

    Args:
        input_path: 输入数据路径。
    """
    return {
        "status": "success",
        "message": f"已处理: {input_path}",
        "items": [
            {"id": "I-001", "name": "条目 A", "value": "100"},
            {"id": "I-002", "name": "条目 B", "value": "200"},
        ],
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Tool 2: progress_tool -- 逐步推送进度
# ---------------------------------------------------------------------------
@mcp.tool(app=AppConfig(resource_uri="ui://mcp-app-ui/progress/index.html"))
async def progress_tool(ctx: Context, input_path: str= None) -> dict[str, Any]:
    """进度工具：逐步推送进度，返回结果。

    Args:
        ctx: fastmcp 上下文（自动注入）。
        input_path: 输入数据路径。
    """
    total = 3
    for i in range(1, total + 1):
        await asyncio.sleep(1)
        await send_progress_with_data(
            ctx,
            progress=float(i),
            total=float(total),
            message=f"步骤 {i}/{total}",
        )

    return {
        "status": "success",
        "message": f"已处理: {input_path}",
        "items": [
            {"id": "I-001", "name": "条目 A", "value": "100"},
            {"id": "I-002", "name": "条目 B", "value": "200"},
        ],
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Tool 3: review_tool -- 推送进度 + 读取源图 + 阻塞等待审核
# ---------------------------------------------------------------------------
@mcp.tool(app=AppConfig(resource_uri="ui://mcp-app-ui/review/index.html"))
async def review_tool(ctx: Context, input_path: str | None = "D:\项目\AI-For-Redesign\代码库\mcp-server-指南\image\mcpserver-duck-src-三者关系.png") -> dict[str, Any]:
    """审核工具：推送进度 -> 读取源图 -> 阻塞等待人工审核 -> 返回最终结果。

    Args:
        ctx: fastmcp 上下文（自动注入）。
        input_path: 输入图片路径（可选，不传则跳过源图读取）。
    """
    total = 3
    for i in range(1, total + 1):
        await asyncio.sleep(1)
        # 第一次推送时携带 image_paths，UI 执行中阶段（TaskWithImage）即可反向调用
        # read_image 加载源图；后续推送无需重复携带（UI 端 ref 去重）。
        ui_event = {"image_paths": [input_path]} if i == 1 and input_path else None
        await send_progress_with_data(
            ctx,
            progress=float(i),
            total=float(total),
            message=f"步骤 {i}/{total}",
            ui_event=ui_event,
        )

    # 通过 read_image 读取源图，base64 data URL 随 final_result 推给 UI 展示
    image_url = None
    image_error = None
    if input_path:
        img = read_image(input_path)
        if "data_base64" in img:
            image_url = f"data:{img['mime_type']};base64,{img['data_base64']}"
        else:
            image_error = img.get("content", [{}])[0].get("text", "图片读取失败")

    # 构造提取结果
    final_result = {
        "status": "success",
        "message": f"已处理: {input_path}",
        "items": [
            {"id": "I-001", "name": "条目 A", "value": "100"},
            {"id": "I-002", "name": "条目 B", "value": "200"},
        ],
        "warnings": [],
    }
    if image_url:
        final_result["image_url"] = image_url
    if image_error:
        final_result["image_error"] = image_error

    # 生成 review_id，推送 review_pending，阻塞等待
    review_id = f"review-{asyncio.get_running_loop().time()}"
    _review_events[review_id] = asyncio.Event()

    await send_progress_with_data(
        ctx,
        progress=1.0,
        total=1.0,
        message="提取完成，等待审核",
        ui_event={
            "review_pending": True,
            "review_id": review_id,
            "tool_name": "review_tool",
            "final_result": final_result,
            # 执行中阶段 TaskWithImage 即可加载源图
            "image_paths": [input_path] if input_path else None,
        },
    )

    # 阻塞等待 submit_review 唤醒
    await _review_events[review_id].wait()

    review_data = _review_results.pop(review_id, {})
    _review_events.pop(review_id, None)

    approved = review_data.get("approved", False)
    # 注意：submit_review 未编辑时 edited_data 为 None（key 存在但值为 None），
    # dict.get 的默认值仅在 key 不存在时生效，因此需单独判空兜底为 final_result
    edited_data = review_data.get("edited_data")
    if edited_data is None:
        edited_data = final_result

    if approved:
        return {"status": "approved", "message": "审核通过", "final_result": "太大了看不了"}
    else:
        return {"status": "rejected", "message": review_data.get("reason", "未提供原因")}


# ---------------------------------------------------------------------------
# Tool 4: submit_review -- UI 反向调用，唤醒阻塞的审核工具
# visibility=["app"]：仅 app 可调用，不暴露给 LLM（避免绕过人工审核）
# ---------------------------------------------------------------------------
@mcp.tool(app=AppConfig(visibility=["app"]))
def submit_review(
    review_id: str,
    approved: bool,
    edited_data: Optional[dict[str, Any]] = None,
    reason: str = "",
) -> dict[str, Any]:
    """提交审核结果，唤醒阻塞中的审核工具。

    Args:
        review_id: 审核会话 ID（由 review_tool 通过 progress.uiEvent.review_id 推送）。
        approved: 是否通过审核。
        edited_data: 用户编辑后的数据（approved=True 时提供）。
        reason: 驳回原因（approved=False 时提供）。
    """
    if review_id not in _review_events:
        return {"status": "error", "message": f"未找到 review_id: {review_id}"}

    _review_results[review_id] = {
        "approved": approved,
        "edited_data": edited_data,
        "reason": reason,
    }
    _review_events[review_id].set()

    return {"status": "ok", "review_id": review_id, "approved": approved}


# ---------------------------------------------------------------------------
# Tool 5: read_image -- UI 反向调用，读取图片为 base64
# visibility=["app"]：仅 app 可调用，不暴露给 LLM
# ---------------------------------------------------------------------------
@mcp.tool(app=AppConfig(visibility=["app"]))
def read_image(path: str) -> dict[str, Any]:
    """读取本地图片，返回 base64 编码数据。

    Args:
        path: 图片文件路径。
    """
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(path)[1].lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}
        mime_type = mime_map.get(ext, "application/octet-stream")
        return {"mime_type": mime_type, "data_base64": data}
    except FileNotFoundError:
        return {"isError": True, "content": [{"type": "text", "text": f"文件不存在: {path}"}]}


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------
def main() -> None:
    """HTTP 启动：默认 127.0.0.1:8000，开启跨域访问（CORS）。"""
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware

    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8000"))
    mcp.run(
        transport="http",
        host=host,
        port=port,
        host_origin_protection=False,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
                # 暴露 MCP 协议响应头，供跨域浏览器客户端读取
                expose_headers=["*"],
            )
        ],
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
