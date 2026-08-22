"""
Base workflow infrastructure - 通用工作流基类。

所有工作流（PFD 拓扑、整厂装置、工艺包等）的统一基类，只提供与具体业务
无关的通用能力：配置存储、专家初始化钩子、宿主交互（进度通知/文件读写）。

PFD 拓扑专用能力（设备/边界并行提取、process_description、equipment_table、
OCRMatcher、TopologyState 输出构建等）直接在具体工作流（如
:class:`~src.agent.workflow.unit.pfd_topology.PFDTopologyWorkflow`）中实现。

子类约定：
    - 覆盖 ``workflow_name``
    - 覆盖 :meth:`_init_experts` 创建自己的专家
    - 覆盖 :meth:`_log_workflow_info` 记录自身配置
    - 实现 :meth:`analyze` 执行具体编排
"""
import threading
from pathlib import Path
from typing import Any, Optional

from duck.content import Content
from duck.host_client import HostClient
from src.core import LoggerMixin, Settings, get_logger
from src.core.utils import to_workspace_path

logger = get_logger(__name__)


class BaseWorkflow(LoggerMixin):
    """全部工作流的通用基类。

    只承载与具体业务无关的通用能力：
        - 配置存储（settings / max_workers）
        - 专家初始化与日志钩子（_init_experts / _log_workflow_info）
        - 宿主交互（content / host_client）：
            - ``content.report_progress`` → :meth:`_report_progress`
            - ``host_client.save_file``   → :meth:`_save_file`
            - ``host_client.get_file``    → :meth:`_get_file`

    Subclasses must:
        - 覆盖 ``workflow_name``
        - 覆盖 :meth:`_init_experts` 创建自己的专家
        - 覆盖 :meth:`_log_workflow_info`
        - 实现 :meth:`analyze`
    """

    workflow_name: str = "base"

    def __init__(
        self,
        settings: Settings,
        max_workers: int = 1,
        content: Optional[Content] = None,
        host_client: Optional[HostClient] = None,
    ) -> None:
        self.settings = settings
        self.max_workers = max(1, int(max_workers))
        self._content = content
        self._host_client = host_client
        self._cancel_event: Optional[threading.Event] = None
        self._temp_files: list[str] = []

        self._init_experts()
        self._log_workflow_info()

    # ------------------------------------------------------------------
    # 钩子：子类覆盖
    # ------------------------------------------------------------------

    def _init_experts(self) -> None:
        """创建工作流所需的专家。子类必须覆盖，默认空实现。"""
        pass

    def _log_workflow_info(self) -> None:
        """记录工作流配置信息。子类覆盖以输出自身信息。"""
        logger.info("=" * 60)
        logger.info(f"Workflow: {self.workflow_name}")
        logger.info(f"max_workers: {self.max_workers}")
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # 公共 API：子类实现
    # ------------------------------------------------------------------

    def analyze(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """执行工作流。子类必须实现具体编排逻辑。"""
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement analyze()"
        )

    def _get_all_experts(self) -> list:
        """返回实例上所有 BaseExpert 属性，便于统一管理。"""
        from src.agent.experts.core.base import BaseExpert

        return [attr for attr in vars(self).values() if isinstance(attr, BaseExpert)]

    # ------------------------------------------------------------------
    # 输入路径解析（宿主存储 -> 本地临时文件）
    # ------------------------------------------------------------------

    def _resolve_input_path(self, path: str) -> str:
        """将输入的图片路径解析为本地路径。

        图片均为调用端渲染到本地的产物（豁免 #5，本地文件读取），
        本地已存在时直接返回原路径，不触碰 HostClient；仅当路径本地不存在时，
        才经由 ``host_client.get_file`` 从宿主存储拉取 bytes 并落本地临时文件。
        """
        if Path(path).exists():
            return path
        if not self._host_client:
            return path
        data = self._host_client.get_file(to_workspace_path(path))
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(
                f"_resolve_input_path 期望图片返回 bytes，但 {path} 返回了 "
                f"{type(data).__name__}"
            )
        import tempfile
        suffix = Path(path).suffix or ""
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(bytes(data))
            temp_path = f.name
        self._temp_files.append(temp_path)
        return temp_path

    def cleanup_temp_files(self) -> None:
        """清理 _resolve_input_path 创建的临时文件。"""
        for path in self._temp_files:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        self._temp_files.clear()

    def _load_image(self, path: str) -> "Image.Image":
        """加载本地图片为 PIL.Image（内存流，且立即加载像素）。

        图片均为本地渲染产物（豁免 #5，本地文件读取），直接读取本地文件，
        不再经由 HostClient。

        加载后立即调用 ``.load()`` 将像素载入内存：同一张图会被并行专家
        （equipment / boundary_node / ...）共享，若保持 PIL 懒加载，多线程并发
        ``.convert()`` 会在共享文件指针上产生竞态，读到错位数据并抛出
        ``unrecognized data stream contents when reading image file``。
        """
        from PIL import Image
        import io

        with open(path, "rb") as f:
            data = f.read()
        img = Image.open(io.BytesIO(data))
        img.load()
        return img

    def _load_pdf_bytes(self, path: str) -> bytes:
        """读取 PDF 为 bytes（供 fitz.open(stream=...) 使用）。

        本地已存在时直接读取本地文件（豁免 #5）；仅当路径本地不存在时，
        才通过 ``host_client.get_file`` 从宿主存储拉取。
        """
        from pathlib import Path

        local = Path(path)
        if local.exists():
            return local.read_bytes()
        if not self._host_client:
            raise FileNotFoundError(f"PDF not found: {path}")
        data = self._host_client.get_file(to_workspace_path(path))
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        raise TypeError(f"_load_pdf_bytes 期望 bytes，但 {path} 返回了 {type(data).__name__}")
