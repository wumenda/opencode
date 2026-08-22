"""MCPHostClient：``duck.host_client.HostClient`` 协议的 HTTP 实现。

有 Workbench Session 上下文时读写平台工作区；没有平台上下文时保持原来的
``POST/GET /files/{path}`` 接口，供下游配合 mock_file_server 独立测试。
"""

from __future__ import annotations

import base64
import logging
import os
import unicodedata
from typing import Optional, Union

import httpx
from fastmcp.server.dependencies import get_context

logger = logging.getLogger(__name__)

PLATFORM_META_KEY = "io.industrial.platform"
WORKSPACE_CONTENT_TYPE = "application/vnd.industrial.platform-workspace-file"


class MCPHostError(RuntimeError):
    """MCPHostClient 请求失败的统一异常。

    Attributes:
        status_code: HTTP 状态码（可能为 None）。
        path: 相关文件路径（可能为 None）。
        code: 服务端返回的结构化错误码（如 ``"NOT_FOUND"``，可能为 None）。
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        path: Optional[str] = None,
        code: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.path = path
        self.code = code


class MCPHostClient:
    """``duck.host_client.HostClient`` 协议的 HTTP 实现。

    支持上下文管理器用法以自动关闭底层连接池::

        with MCPHostClient() as client:
            client.save_file("config.json", {"a": 1})
    """

    def __init__(
        self,
        *,
        base_url: str = "http://10.30.70.120:9000",
        timeout: float = 30.0,
        client: Optional[httpx.Client] = None,
    ) -> None:
        # 无平台上下文时沿用原文件服务，方便下游独立使用 mock_file_server；
        # 有平台上下文时才访问当前 Session 工作区。
        self._base_url = base_url.rstrip("/")
        self._platform_base_url = os.getenv(
            "PLATFORM_BROKER_URL", "http://127.0.0.1:8200/"
        ).rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)
        # 仅在内部创建 client 时负责关闭，外部传入的由调用方管理
        self._owns_client = client is None

    # ------------------------------------------------------------------
    # 资源管理
    # ------------------------------------------------------------------
    def close(self) -> None:
        """关闭底层连接池。仅关闭内部创建的 client，外部传入的不关闭。"""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "MCPHostClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self._base_url}/files/{path.lstrip('/')}"

    def _platform_request(
        self, path: str
    ) -> Optional[tuple[str, dict[str, str]]]:
        try:
            extras = get_context().request_context.meta.model_extra
            capability = extras.get(PLATFORM_META_KEY).get("capability")
        except (AttributeError, RuntimeError):
            return None
        if not isinstance(capability, str) or not capability:
            return None
        # Windows os.path.join() 产生的反斜杠只在发请求时转成逻辑路径。
        logical_path = unicodedata.normalize("NFC", path.replace("\\", "/"))
        encoded_path = base64.urlsafe_b64encode(logical_path.encode("utf-8"))
        encoded_path = encoded_path.rstrip(b"=").decode("ascii")
        url = (
            f"{self._platform_base_url}/internal/platform/workspace/files/"
            f"{encoded_path}"
        )
        return url, {"Authorization": f"Bearer {capability}"}

    def _raise_for_status(self, resp: httpx.Response, path: Optional[str], op: str) -> None:
        """状态码 >= 400 时抛出友好异常。404 抛 FileNotFoundError，其余抛 McpHostError。"""
        if resp.status_code < 400:
            return
        code: Optional[str] = None
        message = resp.text
        try:
            data = resp.json()
            if isinstance(data, dict):
                code = data.get("code")
                message = data.get("error", message)
        except (ValueError, httpx.DecodingError):
            pass
        if resp.status_code == 404:
            raise FileNotFoundError(f"MCPHostClient.{op}: {path or resp.url} 不存在")
        raise MCPHostError(
            f"MCPHostClient.{op} failed: {resp.status_code} {message}",
            status_code=resp.status_code,
            path=path,
            code=code,
        )

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------
    def save_file(
        self,
        path: str,
        data: Union[dict, str, bytes],
        *,
        kind: str = "auto",
    ) -> None:
        """保存文件到当前 Session 工作区或原 mock_file_server。

        Args:
            path: 文件路径（如 ``config.json``、``readme.md``）。
            data: 文件内容，支持 dict / str / bytes。
            kind: 文件类型，决定发送方式：
                - ``"json"``:  发送 dict。
                - ``"text"``:  发送 UTF-8 文本。
                - ``"bytes"``: 发送原始字节。
                - ``"auto"``:  根据 data 类型自动判断（默认）。

        Raises:
            TypeError: data 类型与 kind 不匹配。
            ValueError: kind 取值非法。
            FileNotFoundError: 父路径相关 404（一般不触发）。
            McpHostError: 其他请求错误。
        """
        platform = self._platform_request(path)
        url, headers = platform if platform is not None else (self._url(path), None)
        request = self._client.put if platform is not None else self._client.post
        if headers is not None:
            headers["Content-Type"] = WORKSPACE_CONTENT_TYPE

        # 确定实际的发送类型
        if kind == "auto":
            if isinstance(data, (bytes, bytearray)):
                kind = "bytes"
            elif isinstance(data, dict):
                kind = "json"
            elif isinstance(data, str):
                kind = "text"
            else:
                raise TypeError(
                    f"save_file 不支持的数据类型: {type(data).__name__}，可选 dict / str / bytes"
                )

        if kind == "json":
            if not isinstance(data, dict):
                raise TypeError(f"kind='json' 需要 dict，得到 {type(data).__name__}")
            resp = request(
                url,
                json=data,
                headers=headers or {"Content-Type": "application/json"},
            )
        elif kind == "text":
            if isinstance(data, str):
                payload = data.encode("utf-8")
            elif isinstance(data, (bytes, bytearray)):
                payload = bytes(data)
            else:
                raise TypeError(f"kind='text' 需要 str 或 bytes，得到 {type(data).__name__}")
            resp = request(
                url,
                content=payload,
                headers=headers or {"Content-Type": "text/plain; charset=utf-8"},
            )
        elif kind == "bytes":
            if not isinstance(data, (bytes, bytearray)):
                raise TypeError(f"kind='bytes' 需要 bytes，得到 {type(data).__name__}")
            resp = request(url, content=bytes(data), headers=headers)
        else:
            raise ValueError(f"不支持的 kind: {kind}，可选值: json / text / bytes / auto")

        self._raise_for_status(resp, path, "save_file")
        logger.info("MCPHostClient 保存文件: %s (kind=%s)", url, kind)

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def get_file(
        self,
        path: str,
        *,
        kind: str = "auto",
    ) -> Union[dict, str, bytes]:
        """从当前 Session 工作区或原 mock_file_server 读取文件。

        Args:
            path: 文件路径。
            kind: 期望的返回类型：
                - ``"json"``:  返回 dict（解析 JSON 响应）。
                - ``"text"``:  返回 str（UTF-8 解码）。
                - ``"bytes"``: 返回 bytes（原始字节）。
                - ``"auto"``:  根据响应 Content-Type 自动判断（默认）。

        Returns:
            dict / str / bytes，取决于 ``kind`` 参数。

        Raises:
            FileNotFoundError: 文件不存在（404）。
            McpHostError: 其他请求错误（含 JSON 解析失败）。
            ValueError: kind 取值非法。
        """
        platform = self._platform_request(path)
        url, headers = platform if platform is not None else (self._url(path), None)
        resp = self._client.get(url, headers=headers)
        if resp.status_code == 404:
            raise FileNotFoundError(f"MCPHostClient.get_file: {url} 不存在")
        self._raise_for_status(resp, path, "get_file")

        if kind == "auto":
            ctype = resp.headers.get("content-type", "")
            if "application/json" in ctype:
                kind = "json"
            elif "text/" in ctype:
                kind = "text"
            else:
                kind = "bytes"

        if kind == "json":
            try:
                return resp.json()
            except (ValueError, httpx.DecodingError) as exc:
                raise MCPHostError(
                    f"get_file 响应不是有效的 JSON: {exc}",
                    status_code=resp.status_code,
                    path=path,
                ) from exc
        elif kind == "text":
            return resp.content.decode("utf-8")
        elif kind == "bytes":
            return resp.content
        else:
            raise ValueError(f"不支持的 kind: {kind}，可选值: json / text / bytes / auto")
