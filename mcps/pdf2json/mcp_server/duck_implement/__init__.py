"""``duck`` 协议的 MCP 实现侧：``Content`` 与 ``HostClient`` 及基础设施。"""

from .content import MCPContent, _send_progress_with_data
from .host_client import HostClient
from ._common import (
    ReviewRegistry,
    _get_ui_html,
    await_user_review,
    get_image_info,
    get_review_registry,
    get_settings,
    pdf_first_page_to_image,
    pdf_to_images_range,
)

__all__ = [
    "MCPContent",
    "HostClient",
    "ReviewRegistry",
    "_get_ui_html",
    "_send_progress_with_data",
    "await_user_review",
    "get_image_info",
    "get_review_registry",
    "get_settings",
    "pdf_first_page_to_image",
    "pdf_to_images_range",
]
