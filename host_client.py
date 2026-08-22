"""HostClient 鸭子类型协议。

为工作流层提供与宿主环境（MCP Server / FastAPI / CLI entry 等）交互的
抽象接口，使工作流与宿主存储/通信层解耦。

- :class:`HostClient`：文件读写，工作流通过它读取输入文件、保存最终结果。

方法约定：
    - ``save_file``: 将 dict（序列化为 JSON）或原始 bytes 写入宿主存储。
    - ``get_file``: 按路径读取文件，返回 dict（JSON）或 bytes（二进制）。

实现示例：
- ``mcp_server.duck_implement.MCPHostClient``：MCP 服务实现，通过 HTTP 与远端
  文件服务交互。
- ``entry._common.EntryHostClient``：CLI entry 脚本实现，独立于 MCP 服务，
  便于按需调整本地存储策略。
"""

from __future__ import annotations

from typing import Union, Protocol, runtime_checkable


@runtime_checkable
class HostClient(Protocol):
    """宿主客户端鸭子类型。

    提供文件读写能力，使工作流能与宿主存储层解耦。
    """

    def save_file(self, path: str, data: Union[dict, bytes]) -> None:
        """将数据保存到宿主存储。

        Args:
            path: 宿主存储中的文件路径（如 ``output/topology.json``）。
            data: dict 会被序列化为 JSON；bytes 直接写入（图片/PDF 等）。
        """
        ...

    def get_file(self, path: str) -> Union[dict, bytes]:
        """从宿主存储读取文件。

        Args:
            path: 宿主存储中的文件路径。

        Returns:
            dict（JSON 文件）或 bytes（二进制文件）。
        """
        ...
