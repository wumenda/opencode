"""MCP Server 基础设施 -- 从原 ``_infra.py``（已移除）迁移的辅助组件。

包含：
- ``_get_ui_html``: 读取并缓存指定 scope 的独立 UI 项目构建产物
- ``get_settings``: Settings 单例（读取 .env + config/providers.yaml）
- ``pdf_to_images_range`` / ``pdf_first_page_to_image``: PDF -> PNG 转换
- ``ReviewRegistry`` / ``get_review_registry`` / ``await_user_review``: 审核工具阻塞/唤醒
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from src._internal import pdf_to_images
from src.core import Settings
from src.core.utils import to_workspace_path

from .content import MCPContent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# _get_ui_html -- 读取并缓存指定 scope 的 UI 构建产物
# ---------------------------------------------------------------------------
# UI HTML 缓存：path -> (html, mtime)。按文件修改时间失效，前端重新构建后无需重启进程。
_UI_HTML_CACHE: dict[str, tuple[str, float]] = {}


def _resolve_ui_html_path(scope: str) -> Path:
    """解析指定 scope 的 UI HTML 路径（``mcp_apps_ui/<scope>-ui/dist/index.html``）。"""
    project_root = Path(__file__).resolve().parent.parent.parent
    return project_root / "mcp_apps_ui" / f"{scope}-ui" / "dist" / "index.html"


def _get_ui_html(tool_name: str, scope: str) -> str:
    """读取指定 scope 的 UI HTML（自包含的审核 UI 单页应用）。

    scope 决定读取哪一个独立 UI 项目构建产物：``apps-ui/<scope>-ui/dist/index.html``。

    在 ``<head>`` 中注入 ``<script>window.__MCP_TOOL_NAME__='...';</script>``，
    使前端在 host 未发送 ``ui/notifications/tool-input`` 时仍能正确路由。

    缓存策略：按文件修改时间（mtime）失效，前端重新构建后无需重启进程。
    注入不污染缓存——缓存存 base HTML，每次调用做字符串替换。
    """
    global _UI_HTML_CACHE
    html_path = _resolve_ui_html_path(scope)
    if not html_path.exists():
        raise FileNotFoundError(f"UI HTML not found: {html_path}")
    mtime = html_path.stat().st_mtime
    key = str(html_path)
    cached = _UI_HTML_CACHE.get(key)
    if cached is None or cached[1] != mtime:
        html = html_path.read_text(encoding="utf-8")
        _UI_HTML_CACHE[key] = (html, mtime)
        logger.info("Loaded UI HTML from %s (%d chars)", html_path, len(html))
    else:
        html = cached[0]
    injection = f'<script>window.__MCP_TOOL_NAME__={json.dumps(tool_name)};</script>'
    if "<head>" not in html:
        logger.warning(
            "UI HTML (%s) 中未找到 <head> 标签，__MCP_TOOL_NAME__ 注入失败，"
            "前端在 host 未发送 tool-input 时将无法路由", html_path,
        )
        return html
    return html.replace("<head>", "<head>" + injection, 1)


# ---------------------------------------------------------------------------
# Settings 单例
# ---------------------------------------------------------------------------
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """加载并缓存 Settings（读取 .env + config/providers.yaml）。

    进程启动后 .env 的改动不会生效，修改后需重启服务。
    """
    global _settings
    if _settings is None:
        _settings = Settings.from_yaml()
        logger.info(
            "Settings loaded (default_provider=%s, model=%s)",
            _settings.default_provider,
            _settings.model,
        )
    return _settings


# ---------------------------------------------------------------------------
# PDF -> 图片转换
# ---------------------------------------------------------------------------
def pdf_image_cache_dir(pdf_path: Path) -> Path:
    """按 PDF 路径哈希返回稳定的缓存目录，避免每次调用新建临时目录。"""
    key = hashlib.md5(str(pdf_path).encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / f"mcp_pdf2img_{key}"


_last_cleanup_time: float = 0.0
_CLEANUP_INTERVAL_SECONDS: float = 600.0  # 10 分钟


def _cleanup_stale_cache_dirs(max_age_hours: float = 24.0) -> None:
    """清理过期的渲染缓存目录（mcp_pdf2img_* / mcp_read_image_*）。

    扫描临时目录，删除最后修改时间超过 max_age_hours 的缓存目录，
    避免处理大量不同 PDF 时磁盘无限累积。

    清理频率由 ``_CLEANUP_INTERVAL_SECONDS`` 限制，避免每次渲染都扫描。
    """
    global _last_cleanup_time
    now = time.time()
    if now - _last_cleanup_time < _CLEANUP_INTERVAL_SECONDS:
        return
    _last_cleanup_time = now
    temp_dir = Path(tempfile.gettempdir())
    cutoff = time.time() - max_age_hours * 3600
    for pattern in ("mcp_pdf2img_*", "mcp_read_image_*"):
        for d in temp_dir.glob(pattern):
            try:
                if d.is_dir() and d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                logger.warning("Failed to clean stale cache dir: %s", d)


def _file_md5(path: Path) -> str:
    """计算文件内容 MD5（1MB 分块），作为渲染图前缀的内容指纹。"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pdf_to_images_range(
    pdf_path: str | Path,
    start_page: int = 0,
    end_page: Optional[int] = None,
    dpi: int = 300,
    work_dir: Optional[str | Path] = None,
    host_client: Optional[Any] = None,
) -> list[str]:
    """把 PDF 指定页范围渲染为 PNG 图片，返回图片路径列表（按页码升序）。

    传入 ``host_client`` 时，PDF 通过 ``host_client.get_file`` 读取（二进制内容），
    写入本地临时文件后交给渲染（fitz 需要文件路径）；本地路径可直接使用。
    渲染产生的 PNG 一律落到本地路径，供后续图片读取（豁免 #5）使用。
    渲染完成后自动删除远端 PDF 临时文件，避免磁盘泄漏。
    """
    _cleanup_stale_cache_dirs()
    pdf_path = Path(pdf_path)

    if host_client is not None:
        # 经 get_file 取 PDF 二进制内容，落临时文件（fitz 需真实文件路径）
        data = host_client.get_file(to_workspace_path(str(pdf_path)))
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(
                f"host_client.get_file 对 PDF 应返回 bytes，实际返回 {type(data).__name__}"
            )
        suffix = pdf_path.suffix or ".pdf"
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, prefix="mcp_pdf_"
        ) as f:
            f.write(bytes(data))
            local_pdf_path = Path(f.name)
        try:
            images = _render_pdf_to_images(
                local_pdf_path, pdf_path, start_page, end_page, dpi, work_dir,
                content_key=hashlib.md5(bytes(data)).hexdigest(),
            )
        finally:
            # 远端 PDF 临时文件渲染后不再需要，删除避免磁盘泄漏
            try:
                local_pdf_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to delete temp PDF: %s", local_pdf_path)
        return images
    else:
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        return _render_pdf_to_images(
            pdf_path, pdf_path, start_page, end_page, dpi, work_dir,
            content_key=_file_md5(pdf_path),
        )


def _render_pdf_to_images(
    local_pdf_path: Path,
    original_pdf_path: Path,
    start_page: int,
    end_page: Optional[int],
    dpi: int,
    work_dir: Optional[str | Path],
    content_key: Optional[str] = None,
) -> list[str]:
    """实际渲染 PDF -> PNG 的公共逻辑。

    图片前缀 = 原始文件名 + 内容指纹：同内容重复渲染覆盖同一批文件（缓存复用、
    目录有界）；内容更新后前缀轮转并清理旧图，避免固定目录内无限累积。
    """
    out_dir = Path(work_dir) if work_dir else pdf_image_cache_dir(original_pdf_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = original_pdf_path.stem
    if content_key:
        prefix = f"{prefix}_{content_key}"
        for old in out_dir.glob(f"{original_pdf_path.stem}_*_page_*.png"):
            try:
                old.unlink()
            except OSError:
                logger.warning("Failed to delete stale render: %s", old)

    images = pdf_to_images(
        pdf_path=str(local_pdf_path),
        output_dir=str(out_dir),
        dpi=dpi,
        image_format="png",
        prefix=prefix,
        start_page=start_page,
        end_page=end_page,
    )
    if not images:
        raise RuntimeError(
            f"PDF->image conversion returned no images for {original_pdf_path} "
            f"(start_page={start_page}, end_page={end_page})"
        )
    return images


def pdf_first_page_to_image(
    pdf_path: str | Path,
    page_index: int = 0,
    dpi: int = 300,
    work_dir: Optional[str | Path] = None,
    host_client: Optional[Any] = None,
) -> str:
    """把 PDF 指定单页渲染为 PNG 图片，返回图片路径。

    ``host_client`` 传透给 :func:`pdf_to_images_range`，PDF 经 ``get_file`` 读取。
    """
    images = pdf_to_images_range(
        pdf_path,
        start_page=page_index,
        end_page=page_index + 1,
        dpi=dpi,
        work_dir=work_dir,
        host_client=host_client,
    )
    return images[0]


# ---------------------------------------------------------------------------
# ReviewRegistry -- 审核工具阻塞/唤醒的内存注册表
# ---------------------------------------------------------------------------
class ReviewRegistry:
    """审核工具阻塞等待 UI 反向调用的内存注册表。

    审核工具（pfd_topology 等）提取完成后调用 ``register(review_id)`` 拿到
    一个 :class:`asyncio.Event`，``await event.wait()`` 阻塞；UI 反向调用
    ``submit_review`` 工具时调用 ``resolve(review_id, data)`` 写入审核数据
    并 ``event.set()`` 唤醒阻塞的工具。工具被唤醒后用 ``get_data`` 取走数据，
    最后 ``cancel`` 清理 entry。

    所有方法在同一个 asyncio 事件循环中调用，dict 操作原子，无需加锁。
    """

    def __init__(self) -> None:
        self._pending: dict[str, dict[str, Any]] = {}

    def register(self, review_id: str) -> "asyncio.Event":
        """注册一个 pending review，返回用于阻塞等待的 Event。"""
        event = asyncio.Event()
        self._pending[review_id] = {"event": event, "data": None}
        return event

    def resolve(self, review_id: str, data: dict[str, Any]) -> bool:
        """UI 提交审核结果时调用：写入 data 并 set event 唤醒阻塞工具。"""
        entry = self._pending.get(review_id)
        if entry is None:
            return False
        entry["data"] = data
        entry["event"].set()
        return True

    def get_data(self, review_id: str) -> Optional[dict[str, Any]]:
        """工具被唤醒后取走审核数据。entry 不删除（由 cancel 清理）。"""
        entry = self._pending.get(review_id)
        return entry["data"] if entry else None

    def cancel(self, review_id: str) -> None:
        """清理 entry。工具正常返回 / 超时 / 被取消时都必须调用。"""
        self._pending.pop(review_id, None)


_review_registry: Optional[ReviewRegistry] = None


def get_review_registry() -> ReviewRegistry:
    """获取全局 ReviewRegistry 单例。"""
    global _review_registry
    if _review_registry is None:
        _review_registry = ReviewRegistry()
    return _review_registry


async def await_user_review(
    content: MCPContent,
    tool_name: str,
    result: dict[str, Any],
    progress: float,
    total: float,
    timeout: float = 3600.0,
    tool_output: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """推送终态结果 + 阻塞等待 UI 反向调用 submit_review。

    审核工具提取完成后调用本协程：
    1. 生成 review_id，通过 progress 通知把终态结果 + review_id 推送给 UI
       （``final_result`` 始终为完整提取结果，供 UI 渲染，不受 ``tool_output`` 影响）；
    2. 阻塞等待 UI 反向调用 ``submit_review`` 工具唤醒；
    3. 返回结果：传入 ``tool_output`` 时返回该轻量摘要（json 地址+元信息），
       否则返回用户审核后的数据（edited_data）或完整 result。
    """
    review_id = str(uuid.uuid4())
    registry = get_review_registry()
    event = registry.register(review_id)

    await content._send_progress_with_data_async(
        progress=progress,
        total=total,
        message=f"{tool_name}: 提取完成，等待用户审核",
        ui_event={
            "review_pending": True,
            "review_id": review_id,
            "tool_name": tool_name,
            "final_result": result,
        },
    )

    try:
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"{tool_name} 审核超时（{timeout}s）")
        data = registry.get_data(review_id)
        if not data or not data.get("approved"):
            reason = (data or {}).get("reason", "未提供原因")
            raise RuntimeError(f"用户驳回审核：{reason}")
        if tool_output is not None:
            return tool_output
        return data.get("edited_data") if data.get("edited_data") is not None else result
    finally:
        registry.cancel(review_id)


# ---------------------------------------------------------------------------
# get_image_info -- 读取图片宽高（供 UI 画布按真实宽高比渲染）
# ---------------------------------------------------------------------------
def get_image_info(image_path: str) -> dict[str, Any]:
    """读取图片宽高（供 UI 画布按真实宽高比渲染）。

    与原 PFDTopologyWorkflow._get_image_info 行为一致；读取失败时回退到默认尺寸。
    """
    try:
        from PIL import Image

        with Image.open(image_path) as img:
            return {"path": image_path, "width": img.width, "height": img.height}
    except (ImportError, OSError) as e:
        logger.warning("get_image_info failed for %s: %r", image_path, e)
        return {"path": image_path, "width": 4096, "height": 2897}
