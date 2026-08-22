"""``python -m mcp_server`` 入口 —— 以 HTTP 模式启动 MCP 服务器。"""

from src.core import setup_logging

from .server import main

if __name__ == "__main__":
    setup_logging()
    main()
