"""
Utility functions for PFD Topology Extractor.

Provides common utility functions used across the application.
"""

import json
import warnings
from pathlib import Path
from typing import Any


def save_json(data: dict[str, Any], output_path: Path) -> None:
    """[Deprecated] 使用 HostClient.save_file 替代。"""
    warnings.warn(
        "save_json is deprecated, use HostClient.save_file instead",
        DeprecationWarning,
        stacklevel=2,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(input_path: Path) -> dict[str, Any]:
    """[Deprecated] 使用 HostClient.get_file 替代。"""
    warnings.warn(
        "load_json is deprecated, use HostClient.get_file instead",
        DeprecationWarning,
        stacklevel=2,
    )
    with open(input_path, "r", encoding="utf-8") as f:
        return json.load(f)


def to_workspace_path(path: str) -> str:
    """把本地绝对路径转为工作区相对逻辑路径（file server 只接受相对路径）。

    - 已是相对路径：原样返回（统一为正斜杠）。
    - 绝对路径：优先相对当前工作目录；cwd 外则去掉盘符/根段，保留可寻址的相对部分。

    用于 ``host_client.get_file`` 等取档前，避免把 ``D:\\...`` 之类的绝对路径
    传给文件服务而被当作路径穿越拒绝。
    """
    p = Path(path)
    if not p.is_absolute():
        return path.replace("\\", "/")
    try:
        return p.relative_to(Path.cwd()).as_posix()
    except ValueError:
        pass
    parts = p.parts
    if len(parts) > 1 and len(parts[0]) == 3 and parts[0][1] == ":":
        return str(Path(*parts[1:])).replace("\\", "/")
    return path.replace("\\", "/")
