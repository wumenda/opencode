"""Content 鸭子类型协议。

为工作流层提供进度推送能力的抽象接口，使工作流与宿主环境
（MCP Server / CLI entry）解耦。

- :class:`Content`：工作流 ``content`` 参数的鸭子类型，描述标准 progress
  通知与携带 ``uiEvent`` 扩展字段的 progress 通知两类方法。

工作流通过 ``content`` 参数推送进度与中间结果；宿主侧负责将调用桥接到
实际的通信通道（MCP session / 日志等）。

实现示例：
- ``mcp_server.duck_implement.MCPContent``：MCP 服务实现，通过
  :func:`asyncio.run_coroutine_threadsafe` 把同步调用桥接到主事件循环上
  的 fastmcp ``Context``。
- ``entry._common.NullContent``：CLI 实现，仅把进度写入日志。
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class Content(Protocol):
    """工作流 ``content`` 参数的鸭子类型。

    方法约定：
        - ``report_progress``: 发送标准 progress 通知（progress/total/message）。
        - ``send_progress_with_data``: 发送携带 ``uiEvent`` 扩展字段的 progress
          通知，``ui_event`` dict 的内容原样作为 ``uiEvent`` 的值传给前端，
          前端直接从 ``progress.uiEvent.<key>`` 读取逐步渲染所需数据。若 host
          未设置 progressToken，回退到标准 report_progress（ui_event 丢弃）。

    推送是 best-effort：异常不应阻塞工作流，实现内部应捕获并记录日志。
    """

    def report_progress(
        self,
        progress: float,
        total: Optional[float] = None,
        message: Optional[str] = None,
    ) -> None:
        """发送标准 progress 通知。

        Args:
            progress: 当前进度值。
            total: 进度总量（可选）。
            message: 人类可读的进度描述（可选）。
        """
        ...

    def send_progress_with_data(
        self,
        progress: float,
        total: Optional[float] = None,
        message: Optional[str] = None,
        ui_event: Optional[dict[str, Any]] = None,
    ) -> None:
        """发送携带 ``uiEvent`` 扩展字段的 progress 通知。

        Args:
            progress: 当前进度值。
            total: 进度总量（可选）。
            message: 人类可读的进度描述（可选）。
            ui_event: 结构化扩展数据，原样作为 ``uiEvent`` 值传给前端。
        """
        ...

