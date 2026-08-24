"""HostClient：通过 opencode host 的 /api/fs/get 与 /api/fs/save 端点实现的 HostClient。

严格对齐 ``host_client.HostClient`` 鸭子类型协议：
    - ``save_file(path, data)``：dict 序列化为 JSON 写入；bytes 按 base64 写入（图片/PDF 等）。
    - ``get_file(path)``：JSON 文件返回 dict；其余返回 bytes（文本由调用方自行解码）。

供下游 MCP server 读取/写入 opencode 工作区文件使用。
"""

from __future__ import annotations

import base64
import json
import urllib.parse
from typing import Union

import requests

BodyValue = Union[dict, bytes]


class HostClient:
    """通过 host HTTP 端点访问工作区文件的 HostClient 实现。"""

    def __init__(
        self,
        base_url: str,
        username: str = "opencode",
        password: str = "",
        workspace: str = "",
        timeout: float = 30.0,
    ) -> None:
        """用 host 服务信息初始化客户端。

        Args:
            base_url: host HTTP 服务基址，例如 ``http://127.0.0.1:4096``。
            username: Basic Auth 用户名（服务端默认 ``opencode``）。
            password: host 口令，对应 ``OPENCODE_SERVER_PASSWORD``。
            workspace: 工作区绝对路径，作为 ``location[directory]`` 查询参数。
            timeout: 请求超时秒数。
        """
        self._base = base_url.rstrip("/")
        self._auth = requests.auth.HTTPBasicAuth(username, password)
        self._workspace = workspace
        self._timeout = timeout

    def _loc_params(self) -> dict[str, str]:
        return {"location[directory]": self._workspace} if self._workspace else {}

    def _url(self, endpoint: str, path: str) -> str:
        quoted = urllib.parse.quote(path, safe="/")
        return f"{self._base}/api/fs/{endpoint}/{quoted}"

    def save_file(self, path: str, data: BodyValue) -> None:
        """保存数据到工作区文件。

        Args:
            path: 相对工作区的文件路径，如 ``output/topology.json``。
            data: dict 序列化为 JSON（utf8）；bytes 按 base64 传输（图片/PDF 等）。
        """
        if isinstance(data, dict):
            payload = {"content": json.dumps(data, ensure_ascii=False), "encoding": "utf8"}
        else:
            payload = {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"}
        resp = requests.put(
            self._url("save", path),
            params=self._loc_params(),
            json=payload,
            auth=self._auth,
            timeout=self._timeout,
        )
        resp.raise_for_status()

    def get_file(self, path: str) -> BodyValue:
        """读取工作区文件。

        Returns:
            dict（JSON 文件）或 bytes（二进制/文本文件）。
        """
        resp = requests.get(
            self._url("get", path),
            params=self._loc_params(),
            auth=self._auth,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data", body)  # 兼容 {location, data} 信封或扁平信封
        if data["encoding"] == "base64":
            return base64.b64decode(data["content"])
        mime = (data.get("mime") or "").lower()
        if "json" in mime or path.endswith(".json"):
            return json.loads(data["content"])
        return data["content"].encode("utf-8")
