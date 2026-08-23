"""MCP Tools —— 封装 src/agent/workflow 下的各能力为 MCP 工具。

每个工具定义为一个普通 async 函数（不依赖全局 ``mcp`` 实例），
由 ``register_tools(mcp)`` 统一注册。工具通过 ``meta.ui.resourceUri``
绑定 ``resources`` 模块中对应的 UI 资源。

工作流的 ``content`` 参数约定为 ``fastmcp.Context``，工作流在其中同步调用
``report_progress``；但 fastmcp v3 的 ``Context.report_progress`` 是 async 协程。
为了让工作流（同步代码，在线程池中执行）能把进度真正推给 MCP 客户端，
:meth:`MCPContent.report_progress` 通过 ``run_coroutine_threadsafe`` 把同步调用
桥接到主事件循环上执行。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

import httpx

from fastmcp import Context, FastMCP

from src.agent.workflow import (
    CompositionTableWorkflow,
    EquipmentAssemblyWorkflow,
    PFDRefluxWorkflow,
    PFDTopologyWorkflow,
    PlantUnitTopologyWorkflow,
    ProcessPackageWorkflow,
)
from src.core import get_logger
from src.core.utils import to_workspace_path
from src.core.infra.exceptions import CancelledByClientError, PFDAnalysisError

from .duck_implement import (
    MCPContent,
    await_user_review,
    get_image_info,
    get_review_registry,
    get_settings,
    pdf_first_page_to_image,
    pdf_to_images_range,
)
from .server import get_host_client
from .resources import (
    COMPOSITION_TABLE_UI_URI,
    EQUIPMENT_ASSEMBLY_UI_URI,
    PFD_REFLUX_UI_URI,
    PFD_TOPOLOGY_UI_URI,
    PLANT_UNIT_UI_URI,
    PROCESS_PACKAGE_UI_URI,
)

logger = get_logger(__name__)


# 各 tool 在 output_file=None 时使用的中文默认文件名
DEFAULT_OUTPUT_FILENAMES: dict[str, str] = {
    "pfd_topology": "PFD图纸拓扑.json",
    "process_package": "工艺包相关信息.json",
    "plant_unit_topology": "全厂装置拓扑.json",
    "equipment_assembly": "塔-反应器装配图相关信息.json",
    "pfd_reflux": "PFD-塔-反应器回流结构相关信息.json",
    "composition_table": "工艺组分表相关信息.json",
}


def _default_output_filename(tool_name: str) -> str:
    """返回默认文件名：基础中文名（如 ``PFD图纸拓扑.json``）。"""
    return DEFAULT_OUTPUT_FILENAMES.get(tool_name, f"{tool_name}_result.json")


def _build_tool_output(
    tool_name: str,
    result: dict[str, Any],
    output_file: Optional[str],
    merged_data: dict[str, Any],
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """构造 tool 返回值：把 workflow 的全部产物合并保存为单个 JSON 文件。

    workflow 不再分散落盘多个散件；本函数一次性把 ``merged_data`` 写入
    ``output_file`` 指定的文件路径。``output_file`` 为完整文件路径（如
    ``"reports/case_001.json"``），为 None 时使用 ``_default_output_filename``
    生成的默认名（基础中文名）。审核 UI 渲染仍通过
    ``await_user_review`` 推送的 ``final_result``（完整 result），与本函数返回的
    摘要互不影响。

    注意：本函数在用户审核通过（approved=True）之后由各工具调用，落盘内容为
    「审核后的结果」——``merged_data`` 顶层含 ``reviewed_data``（用户编辑后的
    edited_data，未编辑时为原始 result）。若审核驳回/超时，工具不会调用本函数，
    因此不落盘。

    Args:
        tool_name: 工作流名称（如 ``"pfd_topology"``）。
        result: workflow 返回的完整结果 dict（用于取 status 等元信息）。
        output_file: 调用方指定的完整文件路径；None 时使用 ``_default_output_filename``
        生成的默认名（基础中文名）。
        merged_data: 合并后的完整数据 dict，将整体写入最终 JSON 文件。
        meta: 额外摘要字段（如 warnings、image_paths 等）。
    """
    final_path = output_file or _default_output_filename(tool_name)
    host = get_host_client()
    if host is not None:
        host.save_file(final_path, merged_data)
    out: dict[str, Any] = {
        "status": result.get("status", "success"),
        "workflow": tool_name,
        "output_file": final_path,
    }
    if meta:
        out.update(meta)
    return out


# ---------------------------------------------------------------------------
# Tool 1: pfd_topology（绑定 UI 资源 ui://pfd-topology/review.html）
# ---------------------------------------------------------------------------
async def pfd_topology(
    ctx: Context,
    pdf_path: str,
    start_page: int = 0,
    end_page: Optional[int] = None,
    dpi: int = 300,
    process_description_path: Optional[str] = None,
    equipment_table_path: Optional[str] = None,
    max_workers: int = 2,
    output_file: Optional[str] = None,
) -> dict[str, Any]:
    """提取 PFD（工艺流程图）PDF 中的设备节点、边界节点与拓扑结构。

    【职责】
    解析 PFD 工艺流程图，识别图中所有设备节点（塔/反应器/换热器/泵等）与
    边界节点（物流进出边界），提取节点间连接关系（拓扑）。
    提取完成后弹出审核 UI，用户审核通过后落盘最终结果。

    【使用场景】
    何时调用:
    - 需要从 PFD 图纸中提取设备清单与连接关系时。
    - 需要提取工艺流程拓扑时。

    何时不调用:
    - 非 PFD 图纸、设备装配图、工艺组分表、工艺包章节文本
    - 输入文件不是 PDF文件

    【参数说明】
    Args:
        pdf_path: PFD 图纸 PDF 的相对路径，必须存在且为 .pdf 文件。
        start_page: 起始页码（0-based，含），默认 0。范围 [0, 总页数)。
        end_page: 结束页码（0-based，不含），None 表示到最后一页；
            传入时必须 > start_page，否则 ValueError。
        dpi: PDF 转图片的渲染 DPI，默认 300。建议范围 [150, 600]：
            过低会丢失小字标签，过高会增加 VLM 调用耗时与显存占用。
        process_description_path: 工艺说明文件路径（可选）。提供后注入 VLM 上下文，
            用于校验节点名称、提升提取准确度。
        equipment_table_path: 工艺设备表文件路径（可选）。提供后用于 tag 校验。
        max_workers: 单页内部提取阶段的并行度，默认 2。范围 [1, 8]：
            1=串行（省显存），>1=并行（提速）。
            注意：跨页之间始终串行执行，本参数仅作用于单页内专家并行。
        output_file: 最终合并 JSON 的完整文件路径；None 时使用默认名
            ``PFD图纸拓扑.json``。
            文件内含 page_graphs / global_graph / image_paths /
            warnings / reviewed_data 等全部产物。

    【返回结果】
    Returns:
        dict[str, Any]，关键字段：
        - status: "success" | "failed"。
        - workflow: "pfd_topology"。
        - output_file: 落盘的 JSON 文件完整路径（审核通过后才有）。
        - page_count: 实际提取的页数。
        - image_paths: 各页渲染图片路径列表。
        - warnings: 警告信息列表（部分页失败会聚合到此处）。
        - errors: 失败时的错误明细（仅 status=failed 时存在）。

    【错误情况】
        返回 status="failed" 时 errors 字段含失败原因，常见情况：
        - PDF 文件不存在/路径错误（FileNotFoundError）。
        - PDF 渲染失败、页码越界（ValueError/RuntimeError）。
        - VLM API 调用失败、网络异常（httpx.HTTPError）。
        - 工作流内部提取失败（PFDAnalysisError），errors 含具体页码。
        - 审核驳回/超时（RuntimeError/TimeoutError），不落盘直接返回 failed。
        部分页失败时仍保存已成功页数据供上游取回（status=failed 但带 output_file）。
    """
    await ctx.info(f"pfd_topology start: {pdf_path} (pages {start_page}..{end_page})")
    content = MCPContent(ctx, asyncio.get_running_loop())
    cancel_event = threading.Event()

    def _run_multi_page() -> dict[str, Any]:
        # PDF -> 图片（工作流内部只接受图片输入）
        image_paths = pdf_to_images_range(
            pdf_path,
            start_page=start_page,
            end_page=end_page,
            dpi=dpi,
            work_dir=None,
            host_client=get_host_client(),
        )
        # 阶段 0.5：批量推送全部页 image_paths + image_infos，UI 立即铺出所有空底图
        image_infos = [get_image_info(p) for p in image_paths]
        total_pages = len(image_paths)
        # 统一全局刻度：每页 5 个阶段，early 事件占刻度起点，保证进度不回落
        total_phases = max(total_pages, 1) * 5
        content.send_progress_with_data(
            0, total=total_phases,
            message=f"PDF 解析完成，共 {total_pages} 页",
            ui_event={
                "event_type": "images_loaded",
                "image_paths": image_paths,
                "image_infos": image_infos,
            },
        )
        workflow = PFDTopologyWorkflow(
            settings=get_settings(),
            max_workers=max_workers,
            process_description_path=process_description_path,
            equipment_table_path=equipment_table_path,
            content=content,
            host_client=get_host_client(),
        )
        results = []
        page_graphs = []
        partial_error: str | None = None
        cancelled = False
        for idx, img_path in enumerate(image_paths):
            if cancel_event.is_set():
                partial_error = f"客户端取消（已完成 {idx}/{total_pages} 页）"
                cancelled = True
                break
            try:
                result = workflow.analyze(
                    image_path=img_path,
                    page_index=start_page + idx,
                    progress_offset_phases=idx * 5,
                    progress_total_phases=total_phases,
                    cancel_event=cancel_event,
                )
            except PFDAnalysisError as e:
                if cancel_event.is_set():
                    partial_error = f"客户端取消（已完成 {idx}/{total_pages} 页）"
                    cancelled = True
                    break
                logger.error(f"pfd_topology: page {idx} extraction failed: {e}")
                partial_error = f"第 {idx + 1} 页提取失败: {e}"
                break
            results.append(result)
            page_graphs.append({
                "page_index": start_page + idx,
                "page_label": f"第 {start_page + idx + 1} 页",
                "pfd_drawing": result.get("pfd_drawing", {}),
            })
            # 推送累积的 partial_page_graphs，UI 逐步渲染已提取的页面拓扑
            content.send_progress_with_data(
                progress=(idx + 1) * 5,
                total=total_phases,
                message=f"第 {idx + 1}/{total_pages} 页提取完成",
                ui_event={
                    "event_type": "page_extraction_complete",
                    "page_index": start_page + idx,
                    "partial_page_graphs": list(page_graphs),
                },
            )

        # 跨页拼接 -> global_graph（即使部分失败也用已完成的页拼接）
        global_graph = PFDTopologyWorkflow.build_global_graph(page_graphs)

        all_warnings: list[str] = []
        for result in results:
            all_warnings.extend(result.get("warnings", []))
        if partial_error:
            all_warnings.append(partial_error)

        workflow.cleanup_temp_files()
        return {
            "version": "1.0.0",
            "workflow": "pfd_topology",
            "status": "cancelled" if cancelled else ("failed" if partial_error else "success"),
            "page_graphs": page_graphs,
            "global_graph": global_graph,
            "image_path": image_paths[0] if image_paths else "",
            "image_paths": image_paths,
            "warnings": all_warnings,
        }

    try:
        result = await asyncio.to_thread(_run_multi_page)
    except asyncio.CancelledError:
        cancel_event.set()
        logger.info("pfd_topology: 客户端取消执行")
        raise
    except (FileNotFoundError, ValueError, RuntimeError, TypeError, httpx.HTTPError) as e:
        logger.error(f"pfd_topology: 输入准备失败（PDF 渲染/文件服务）: {e}")
        return {
            "status": "failed",
            "workflow": "pfd_topology",
            "errors": [str(e)],
            "warnings": [],
        }
    if result.get("status") in ("failed", "cancelled"):
        # 部分页失败/取消：仍保存已成功页数据供上游取回，返回 failed/cancelled + 文件地址（不进审核）
        return await asyncio.to_thread(
            _build_tool_output,
            "pfd_topology",
            result,
            output_file,
            {
                "version": result.get("version", "1.0.0"),
                "workflow": "pfd_topology",
                "page_graphs": result.get("page_graphs", []),
                "global_graph": result.get("global_graph", {}),
                "image_paths": result.get("image_paths", []),
                "warnings": result.get("warnings", []),
            },
            meta={
                "page_count": len(result.get("page_graphs", [])),
                "image_paths": result.get("image_paths", []),
                "warnings": result.get("warnings", []),
            },
        )
    try:
        # 语义 B：审核通过前不落盘；await_user_review 返回审核后的结果（edited_data 或 result）
        reviewed = await await_user_review(
            content,
            tool_name="pfd_topology",
            result=result,
            progress=float(len(result.get("page_graphs", []))),
            total=float(len(result.get("page_graphs", []))),
        )
    except (RuntimeError, TimeoutError) as e:
        # 审核驳回/超时：不落盘
        logger.error(f"pfd_topology: 审核链路失败，不落盘: {e}")
        return {
            "status": "failed",
            "workflow": "pfd_topology",
            "errors": [str(e)],
            "warnings": [],
        }
    return await asyncio.to_thread(
        _build_tool_output,
        "pfd_topology",
        result,
        output_file,
        # 合并后的单文件数据：page_graphs + global_graph + 元信息 + 审核后的 reviewed_data
        {
            "version": result.get("version", "1.0.0"),
            "workflow": "pfd_topology",
            "page_graphs": result.get("page_graphs", []),
            "global_graph": result.get("global_graph", {}),
            "image_paths": result.get("image_paths", []),
            "warnings": result.get("warnings", []),
            "reviewed_data": reviewed,
        },
        meta={
            "page_count": len(result.get("page_graphs", [])),
            "image_paths": result.get("image_paths", []),
            "warnings": result.get("warnings", []),
        },
    )
    


# ---------------------------------------------------------------------------
# Tool 2: process_package（绑定 UI 资源 ui://process-package/review.html）
# ---------------------------------------------------------------------------
async def process_package(
    ctx: Context,
    pdf_path: str,
    chapter_index: Optional[int] = None,
    chapter_title: Optional[str] = None,
    output_file: Optional[str] = None,
) -> dict[str, Any]:
    """从工艺包 PDF 中按章节提取结构化工序说明与反应方程式。

    【使用场景】
    何时调用:
    - 需要从工艺包文档提取某章节的工序说明/反应方程式时。
    - 需要 PFD 之外的工艺背景文本作为其他工具的上下文补充时。

    何时不调用:
    - 输入是 PFD
    - 同时缺 chapter_index 和 chapter_title → 必须至少传一个，否则参数校验失败。
    - 章节序号或标题在 PDF 中不存在 → 返回 failed，需换关键词重试。

    【参数说明】
    Args:
        pdf_path: 工艺包 PDF 的绝对或相对路径，必须存在且为 .pdf 文件。
        chapter_index: 顶层章节序号（1-based 正整数，如 3 表示第 3 章）。
            与 chapter_title 二选一必填；同时传入时以本参数为准。
        chapter_title: 章节标题关键词（子串匹配，大小写不敏感，如 "反应工序"）。
            与 chapter_index 二选一必填。
        output_file: 最终合并 JSON 的完整文件路径；None 时使用默认名
            ``工艺包相关信息.json``。
            文件内含 locator / matched_sections /
            filtered_text / extracted / reviewed_data 等全部产物。

    【返回结果】
    Returns:
        dict[str, Any]，关键字段：
        - status: "success" | "failed"。
        - workflow: "process_package"。
        - output_file: 落盘的 JSON 文件完整路径（审核通过后才有）。
        - matched_sections: 命中的章节信息（标题、页码范围等）。
        - warnings: 警告信息列表。
        - errors: 失败时的错误明细（仅 status=failed 时存在）。

    【错误情况】
        返回 status="failed" 时 errors 字段含失败原因，常见情况：
        - chapter_index 与 chapter_title 同时缺失 → 参数校验直接返回 failed。
        - PDF 文件不存在/路径错误（FileNotFoundError）。
        - 章节序号或标题在 PDF 中未命中（PFDAnalysisError）。
        - VLM API 调用失败、网络异常（httpx.HTTPError）。
        - 审核驳回/超时（RuntimeError/TimeoutError），不落盘直接返回 failed。
    """
    if chapter_index is None and not chapter_title:
        logger.warning(
            "process_package called without chapter_index or chapter_title; "
            "expected at least one of them"
        )
        return {
            "status": "failed",
            "workflow": "process_package",
            "errors": [
                "参数校验失败：chapter_index 与 chapter_title 至少需要传入一个。"
                "chapter_index 为顶层章节序号(1-based, 整数)；"
                "chapter_title 为章节标题关键词(子串匹配, 大小写不敏感)。"
                "请补充其中一个参数后重试。"
            ],
            "warnings": [],
        }
    await ctx.info(f"process_package start: {pdf_path}")
    content = MCPContent(ctx, asyncio.get_running_loop())
    cancel_event = threading.Event()
    try:
        workflow = ProcessPackageWorkflow(
            settings=get_settings(),
            content=content,
            host_client=get_host_client(),
        )
        result = await asyncio.to_thread(
            workflow.analyze,
            pdf_path=pdf_path,
            chapter_index=chapter_index,
            chapter_title=chapter_title,
            cancel_event=cancel_event,
        )
    except asyncio.CancelledError:
        cancel_event.set()
        logger.info("process_package: 客户端取消执行")
        raise
    except PFDAnalysisError as e:
        if cancel_event.is_set():
            logger.info("process_package: 客户端取消执行")
            return {
                "status": "cancelled",
                "workflow": "process_package",
                "errors": ["客户端取消执行"],
                "warnings": [],
            }
        logger.error(f"process_package extraction failed: {e}")
        return {
            "status": "failed",
            "workflow": "process_package",
            "errors": [str(e)],
            "warnings": [],
        }
    except (FileNotFoundError, ValueError, RuntimeError, TypeError, httpx.HTTPError) as e:
        logger.error(f"process_package: 输入准备失败（PDF 渲染/文件服务）: {e}")
        return {
            "status": "failed",
            "workflow": "process_package",
            "errors": [str(e)],
            "warnings": [],
        }
    try:
        # 语义 B：审核通过前不落盘；await_user_review 返回审核后的结果（edited_data 或 result）
        reviewed = await await_user_review(
            content, tool_name="process_package", result=result, progress=1.0, total=1.0,
        )
    except (RuntimeError, TimeoutError) as e:
        # 审核驳回/超时：不落盘
        logger.error(f"process_package: 审核链路失败，不落盘: {e}")
        return {
            "status": "failed",
            "workflow": "process_package",
            "errors": [str(e)],
            "warnings": [],
        }
    return await asyncio.to_thread(
        _build_tool_output,
        "process_package",
        result,
        output_file,
        # 合并后的单文件数据：完整 result + extracted + filtered_text + 审核后的 reviewed_data
        {
            "version": "1.0.0",
            "workflow": "process_package",
            "pdf_path": result.get("pdf_path", ""),
            "locator": result.get("locator", ""),
            "total_pages": result.get("total_pages", 0),
            "matched_sections": result.get("matched_sections", []),
            "all_matched_page_numbers": result.get("all_matched_page_numbers", []),
            "filtered_text_length": result.get("filtered_text_length", 0),
            "filtered_text": result.get("filtered_text", ""),
            "extracted": result.get("expert_outputs", {}).get("process_package", {}),
            "warnings": result.get("warnings", []),
            "reviewed_data": reviewed,
        },
        meta={
            "matched_sections": result.get("matched_sections", []),
            "warnings": result.get("warnings", []),
        },
    )


# ---------------------------------------------------------------------------
# Tool 3: plant_unit_topology（绑定 UI 资源 ui://plant-unit/review.html）
# ---------------------------------------------------------------------------
async def plant_unit_topology(
    ctx: Context,
    pdf_path: str,
    page_index: int = 0,
    dpi: int = 300,
    general_topology_mode: str = "one_by_one",
    max_workers: int = 1,
    output_file: Optional[str] = None,
) -> dict[str, Any]:
    """提取全厂装置布置图中的装置节点与装置间拓扑关系。

    【职责】
    解析全厂装置布置图，VLM 自动判别图纸类型（通用布置图 / 密集布置图），
    再路由到对应专家路径提取装置节点（如常压蒸馏装置、催化裂化装置等）与
    装置间物流连接关系（拓扑）。提取完成后弹出审核 UI，用户审核通过后
    落盘最终结果。

    【使用场景】
    何时调用:
    - 需要从全厂总平面/布置图获取装置清单与装置间连接关系时。
    - 需要全厂级拓扑（区别于单套 PFD 的设备级拓扑）时。
    - 后续全厂物料平衡、组分流向分析需要装置拓扑作为骨架时。

    何时不调用:
    - 输入文件不是 PDF（如已是图片）→ 本工具仅接受 PDF 路径。

    【参数说明】
    Args:
        pdf_path: 全厂装置布置图 PDF 的绝对或相对路径，必须存在且为 .pdf 文件。
        page_index: 要分析的页码（0-based），默认 0（第 1 页）。
            多页 PDF 仅分析指定单页，不支持页范围。
        dpi: PDF 转图片的渲染 DPI，默认 300。建议范围 [150, 600]：
            过低会丢失小字标签，过高会增加 VLM 调用耗时与显存占用。
        general_topology_mode: 通用图纸的拓扑提取模式，默认 "one_by_one"。
            可选值:
            - "one_by_one": 逐装置识别后聚合（准确度高，耗时较长）。
            - "all_in_one": 整图单次 VLM 调用提取（快但易遗漏密集区域）。
        max_workers: 并行度，默认 1。范围 [1, 8]：仅 one_by_one 模式生效，
            all_in_one 模式恒为单次调用。
        output_file: 最终合并 JSON 的完整文件路径；None 时使用默认名
            ``全厂装置拓扑.json``。
            文件内含 drawing_type / plant_units /
            plant_unit_topology / plant_unit_drawing / reviewed_data 等全部产物。

    【返回结果】
    Returns:
        dict[str, Any]，关键字段：
        - status: "success" | "failed"。
        - workflow: "plant_unit_topology"。
        - output_file: 落盘的 JSON 文件完整路径（审核通过后才有）。
        - image_path: 渲染后的图片路径。
        - warnings: 警告信息列表。
        - errors: 失败时的错误明细（仅 status=failed 时存在）。

    【错误情况】
        返回 status="failed" 时 errors 字段含失败原因，常见情况：
        - PDF 文件不存在/路径错误（FileNotFoundError）。
        - PDF 渲染失败、页码越界（ValueError/RuntimeError）。
        - VLM API 调用失败、网络异常（httpx.HTTPError）。
        - 工作流内部提取失败（PFDAnalysisError）。
        - 审核驳回/超时（RuntimeError/TimeoutError），不落盘直接返回 failed。
    """
    await ctx.info(f"plant_unit_topology start: {pdf_path} (page {page_index})")
    content = MCPContent(ctx, asyncio.get_running_loop())
    cancel_event = threading.Event()

    def _run() -> dict[str, Any]:
        # PDF -> 图片（工作流内部只接受图片输入）
        image_path = pdf_first_page_to_image(
            pdf_path, page_index=page_index, dpi=dpi, work_dir=None,
            host_client=get_host_client(),
        )
        # 阶段 0：推送 image_paths + image_infos，UI 立即加载底图（与 pfd_topology 行为一致）
        image_infos = [get_image_info(image_path)]
        content.send_progress_with_data(
            0, total=4,
            message=f"PDF 解析完成，已生成图片",
            ui_event={
                "event_type": "images_loaded",
                "image_paths": [image_path],
                "image_infos": image_infos,
            },
        )
        workflow = PlantUnitTopologyWorkflow(
            settings=get_settings(),
            max_workers=max_workers,
            general_topology_mode=general_topology_mode,
            content=content,
            host_client=get_host_client(),
        )
        try:
            result = workflow.analyze(image_path=image_path, cancel_event=cancel_event)
        except PFDAnalysisError as e:
            if cancel_event.is_set():
                logger.info("plant_unit_topology: 客户端取消执行")
                return {"status": "cancelled", "workflow": "plant_unit_topology", "errors": ["客户端取消执行"], "warnings": [], "image_path": image_path}
            logger.error(f"plant_unit_topology extraction failed: {e}")
            return {"status": "failed", "workflow": "plant_unit_topology", "errors": [str(e)], "warnings": [], "image_path": image_path}
        result["image_path"] = image_path
        return result

    try:
        result = await asyncio.to_thread(_run)
    except asyncio.CancelledError:
        cancel_event.set()
        logger.info("plant_unit_topology: 客户端取消执行")
        raise
    except (FileNotFoundError, ValueError, RuntimeError, TypeError, httpx.HTTPError) as e:
        logger.error(f"plant_unit_topology: 输入准备失败（PDF 渲染/文件服务）: {e}")
        return {
            "status": "failed",
            "workflow": "plant_unit_topology",
            "errors": [str(e)],
            "warnings": [],
        }
    if result.get("status") in ("failed", "cancelled"):
        return result
    try:
        # 语义 B：审核通过前不落盘；await_user_review 返回审核后的结果（edited_data 或 result）
        reviewed = await await_user_review(
            content, tool_name="plant_unit_topology", result=result, progress=1.0, total=1.0,
        )
    except (RuntimeError, TimeoutError) as e:
        # 审核驳回/超时：不落盘
        logger.error(f"plant_unit_topology: 审核链路失败，不落盘: {e}")
        return {
            "status": "failed",
            "workflow": "plant_unit_topology",
            "errors": [str(e)],
            "warnings": [],
        }
    return await asyncio.to_thread(
        _build_tool_output,
        "plant_unit_topology",
        result,
        output_file,
        # 合并后的单文件数据：完整 result（含 expert_outputs 各子产物 + plant_unit_drawing）+ reviewed_data
        {
            "version": "1.0.0",
            "workflow": "plant_unit_topology",
            "drawing_type": result.get("drawing_type", ""),
            "plant_unit_drawing": result.get("plant_unit_drawing", {}),
            "expert_outputs": result.get("expert_outputs", {}),
            "image_path": result.get("image_path", ""),
            "warnings": result.get("warnings", []),
            "reviewed_data": reviewed,
        },
        meta={
            "image_path": result.get("image_path", ""),
            "warnings": result.get("warnings", []),
        },
    )


# ---------------------------------------------------------------------------
# Tool 4: equipment_assembly（绑定 UI 资源 ui://equipment-assembly/review.html）
# ---------------------------------------------------------------------------
async def equipment_assembly(
    ctx: Context,
    pdf_path: str,
    page_index: int = 0,
    dpi: int = 300,
    equipment_id: str = "",
    equipment_type: Optional[str] = None,
    output_file: Optional[str] = None,
) -> dict[str, Any]:
    """提取塔/反应器等设备的装配图信息（内部结构、规格、材质等）。

    【职责】
    解析设备装配图 PDF，VLM 自动判别设备类型（板式塔 / 填料塔 / 反应器），
    路由到对应专家提取装配信息：塔板数、填料层、进料/出料口位置、
    材质、操作温度/压力等。提取完成后弹出审核 UI，用户审核通过后落盘最终结果。

    【使用场景】
    何时调用:
    - 需要从设备装配图获取塔/反应器内部结构详情时。
    - 需要设备规格参数（塔板数、填料高度、材质等）作为仿真或设计输入时。
    - 已知设备位号（如 T-101、R-201）需要回填上下文时。

    何时不调用:
    - 输入文件不是 PDF（如已是图片）→ 本工具仅接受 PDF 路径。

    【参数说明】
    Args:
        pdf_path: 设备装配图 PDF 的绝对或相对路径，必须存在且为 .pdf 文件。
        page_index: 要分析的页码（0-based），默认 0（第 1 页）。
            多页 PDF 仅分析指定单页，不支持页范围。
        dpi: PDF 转图片的渲染 DPI，默认 300。建议范围 [150, 600]：
            过低会丢失尺寸标注/小字标签，过高会增加 VLM 调用耗时与显存占用。
        equipment_id: 设备位号/样本 id（可选，如 "T-101"、"R-201"）。
            用于上下文回填，提升 VLM 对设备身份的识别准确度。
        equipment_type: 设备类型（可选，如 "column_tray"、"column_packed"、
            "reactor"）。传入时跳过 VLM 类型判别，直接路由到对应专家提取。
            None 时由 VLM 自动判别设备类型。
        output_file: 最终合并 JSON 的完整文件路径；None 时使用默认名
            ``塔-反应器装配图相关信息.json``。
            文件内含 equipment_type / type_detection /
            assembly / image_path / reviewed_data 等全部产物。

    【返回结果】
    Returns:
        dict[str, Any]，关键字段：
        - status: "success" | "failed"。
        - workflow: "equipment_assembly"。
        - output_file: 落盘的 JSON 文件完整路径（审核通过后才有）。
        - equipment_type: 识别出的设备类型（"plate_tower" / "packed_tower" /
          "reactor" / "unknown"）。
        - image_path: 渲染后的图片路径。
        - warnings: 警告信息列表。
        - errors: 失败时的错误明细（仅 status=failed 时存在）。

    【错误情况】
        返回 status="failed" 时 errors 字段含失败原因，常见情况：
        - PDF 文件不存在/路径错误（FileNotFoundError）。
        - PDF 渲染失败、页码越界（ValueError/RuntimeError）。
        - VLM API 调用失败、网络异常（httpx.HTTPError）。
        - 工作流内部提取失败（PFDAnalysisError），如设备类型无法识别。
        - 审核驳回/超时（RuntimeError/TimeoutError），不落盘直接返回 failed。
    """
    await ctx.info(f"equipment_assembly start: {pdf_path} (page {page_index})")
    content = MCPContent(ctx, asyncio.get_running_loop())
    cancel_event = threading.Event()

    def _run() -> dict[str, Any]:
        # PDF -> 图片（工作流内部只接受图片输入）
        image_path = pdf_first_page_to_image(
            pdf_path, page_index=page_index, dpi=dpi, work_dir=None,
            host_client=get_host_client(),
        )
        # PDF 解析完成：推送 images_loaded，驱动 UI 立即请求并显示装配图底图（与 pfd_topology 一致）
        content.send_progress_with_data(
            0, total=3,
            message=f"PDF 解析完成，装配图已加载（第 {page_index + 1} 页）",
            ui_event={
                "event_type": "images_loaded",
                "image_paths": [image_path],
                "image_infos": [get_image_info(image_path)],
            },
        )
        workflow = EquipmentAssemblyWorkflow(
            settings=get_settings(),
            content=content,
            host_client=get_host_client(),
        )
        try:
            result = workflow.analyze(
                image_path=image_path,
                equipment_id=equipment_id,
                equipment_type=equipment_type,
                cancel_event=cancel_event,
            )
        except PFDAnalysisError as e:
            if cancel_event.is_set():
                logger.info("equipment_assembly: 客户端取消执行")
                return {"status": "cancelled", "workflow": "equipment_assembly", "errors": ["客户端取消执行"], "warnings": [], "image_path": image_path}
            logger.error(f"equipment_assembly extraction failed: {e}")
            return {"status": "failed", "workflow": "equipment_assembly", "errors": [str(e)], "warnings": [], "image_path": image_path}
        result["image_path"] = image_path
        return result

    try:
        result = await asyncio.to_thread(_run)
    except asyncio.CancelledError:
        cancel_event.set()
        logger.info("equipment_assembly: 客户端取消执行")
        raise
    except (FileNotFoundError, ValueError, RuntimeError, TypeError, httpx.HTTPError) as e:
        logger.error(f"equipment_assembly: 输入准备失败（PDF 渲染/文件服务）: {e}")
        return {
            "status": "failed",
            "workflow": "equipment_assembly",
            "errors": [str(e)],
            "warnings": [],
        }
    if result.get("status") in ("failed", "cancelled"):
        return result
    try:
        # 语义 B：审核通过前不落盘；await_user_review 返回审核后的结果（edited_data 或 result）
        reviewed = await await_user_review(
            content, tool_name="equipment_assembly", result=result, progress=1.0, total=1.0,
        )
    except (RuntimeError, TimeoutError) as e:
        # 审核驳回/超时：不落盘
        logger.error(f"equipment_assembly: 审核链路失败，不落盘: {e}")
        return {
            "status": "failed",
            "workflow": "equipment_assembly",
            "errors": [str(e)],
            "warnings": [],
        }
    return await asyncio.to_thread(
        _build_tool_output,
        "equipment_assembly",
        result,
        output_file,
        # 合并后的单文件数据：完整 result（含 type_detection + assembly）+ reviewed_data
        {
            "version": "1.0.0",
            "workflow": "equipment_assembly",
            "equipment_id": result.get("equipment_id", ""),
            "equipment_type": result.get("equipment_type", "unknown"),
            "type_detection": result.get("type_detection", {}),
            "assembly": result.get("assembly", {}),
            "image_path": result.get("image_path", ""),
            "warnings": result.get("warnings", []),
            "reviewed_data": reviewed,
        },
        meta={
            "image_path": result.get("image_path", ""),
            "warnings": result.get("warnings", []),
        },
    )


# ---------------------------------------------------------------------------
# Tool 6: pfd_reflux（绑定 UI 资源 ui://pfd-reflux/review.html）
# ---------------------------------------------------------------------------
async def pfd_reflux(
    ctx: Context,
    pdf_path: str,
    page_index: int = 0,
    dpi: int = 300,
    process_description: str = "",
    output_file: Optional[str] = None,
) -> dict[str, Any]:
    """提取 PFD 图纸中塔与反应器的回流结构信息及操作条件。

    【职责】
    解析 PFD 图纸，识别图中所有塔（Tower/Column）和反应器（Reactor），
    判断每个设备是否存在回流结构（物料流出后又回到设备自身）。对存在回流
    的塔，进一步判断塔顶是否有冷凝器、塔釜是否有再沸器、回流管线的回流量，
    并提取塔/反应器操作条件（温度、压力）。提取完成后弹出审核 UI，
    用户审核通过后落盘最终结果。

    【使用场景】
    何时调用:
    - 需要从 PFD 识别塔/反应器的回流配置（冷凝器/再沸器/回流量）时。
    - 需要塔/反应器操作条件（温度、压力）作为仿真或设计输入时。
    - 已用 pfd_topology 提取拓扑，需要进一步分析关键设备的回流细节时。

    何时不调用:
    - 输入文件不是 PDF（如已是图片）→ 本工具仅接受 PDF 路径。

    【参数说明】
    Args:
        pdf_path: PFD 图纸 PDF 的绝对或相对路径，必须存在且为 .pdf 文件。
        page_index: 要分析的页码（0-based），默认 0（第 1 页）。
            多页 PDF 仅分析指定单页，不支持页范围。
        dpi: PDF 转图片的渲染 DPI，默认 300。建议范围 [150, 600]：
            过低会丢失管线/标签，过高会增加 VLM 调用耗时与显存占用。
        process_description: 工艺说明文本（可选）。提供后注入 VLM 上下文，
            用于校验回流判断、提升操作条件提取准确度。
        output_file: 最终合并 JSON 的完整文件路径；None 时使用默认名
            ``PFD-塔-反应器回流结构相关信息.json``。
            需稳定路径请显式传入。文件内含 towers / reactors /
            expert_outputs / image_path / reviewed_data 等全部产物。

    【返回结果】
    Returns:
        dict[str, Any]，关键字段：
        - status: "success" | "failed"。
        - workflow: "pfd_reflux"。
        - output_file: 落盘的 JSON 文件完整路径（审核通过后才有）。
        - towers: 识别出的塔列表（含回流结构、冷凝器、再沸器、回流量等）。
        - reactors: 识别出的反应器列表（含操作条件）。
        - image_path: 渲染后的图片路径。
        - warnings: 警告信息列表。
        - errors: 失败时的错误明细（仅 status=failed 时存在）。

    【错误情况】
        返回 status="failed" 时 errors 字段含失败原因，常见情况：
        - PDF 文件不存在/路径错误（FileNotFoundError）。
        - PDF 渲染失败、页码越界（ValueError/RuntimeError）。
        - VLM API 调用失败、网络异常（httpx.HTTPError）。
        - 工作流内部提取失败（PFDAnalysisError），如未识别到任何塔/反应器。
        - 审核驳回/超时（RuntimeError/TimeoutError），不落盘直接返回 failed。
    """
    await ctx.info(f"pfd_reflux start: {pdf_path} (page {page_index})")
    content = MCPContent(ctx, asyncio.get_running_loop())
    cancel_event = threading.Event()

    def _run() -> dict[str, Any]:
        # PDF -> 图片（工作流内部只接受图片输入）
        image_path = pdf_first_page_to_image(
            pdf_path, page_index=page_index, dpi=dpi, work_dir=None,
            host_client=get_host_client(),
        )
        workflow = PFDRefluxWorkflow(
            settings=get_settings(),
            process_description=process_description,
            content=content,
            host_client=get_host_client(),
        )
        try:
            result = workflow.analyze(image_path=image_path, cancel_event=cancel_event)
        except PFDAnalysisError as e:
            if cancel_event.is_set():
                logger.info("pfd_reflux: 客户端取消执行")
                return {"status": "cancelled", "workflow": "pfd_reflux", "errors": ["客户端取消执行"], "warnings": [], "image_path": image_path}
            logger.error(f"pfd_reflux extraction failed: {e}")
            return {"status": "failed", "workflow": "pfd_reflux", "errors": [str(e)], "warnings": [], "image_path": image_path}
        result["image_path"] = image_path
        return result

    try:
        result = await asyncio.to_thread(_run)
    except asyncio.CancelledError:
        cancel_event.set()
        logger.info("pfd_reflux: 客户端取消执行")
        raise
    except (FileNotFoundError, ValueError, RuntimeError, TypeError, httpx.HTTPError) as e:
        logger.error(f"pfd_reflux: 输入准备失败（PDF 渲染/文件服务）: {e}")
        return {
            "status": "failed",
            "workflow": "pfd_reflux",
            "errors": [str(e)],
            "warnings": [],
        }
    if result.get("status") in ("failed", "cancelled"):
        return result
    try:
        # 语义 B：审核通过前不落盘；await_user_review 返回审核后的结果（edited_data 或 result）
        reviewed = await await_user_review(
            content, tool_name="pfd_reflux", result=result, progress=1.0, total=1.0,
        )
    except (RuntimeError, TimeoutError) as e:
        # 审核驳回/超时：不落盘
        logger.error(f"pfd_reflux: 审核链路失败，不落盘: {e}")
        return {
            "status": "failed",
            "workflow": "pfd_reflux",
            "errors": [str(e)],
            "warnings": [],
        }
    return await asyncio.to_thread(
        _build_tool_output,
        "pfd_reflux",
        result,
        output_file,
        # 合并后的单文件数据：完整 result（含 towers + reactors + expert_outputs）+ reviewed_data
        {
            "version": "1.0.0",
            "workflow": "pfd_reflux",
            "expert_outputs": result.get("expert_outputs", {}),
            "towers": result.get("towers", []),
            "reactors": result.get("reactors", []),
            "image_path": result.get("image_path", ""),
            "warnings": result.get("warnings", []),
            "reviewed_data": reviewed,
        },
        meta={
            "image_path": result.get("image_path", ""),
            "warnings": result.get("warnings", []),
        },
    )


# ---------------------------------------------------------------------------
# Tool 7: composition_table（绑定 UI 资源 ui://composition-table/review.html）
# ---------------------------------------------------------------------------
async def composition_table(
    ctx: Context,
    pdf_path: str,
    start_page: int = 0,
    end_page: Optional[int] = None,
    dpi: int = 300,
    output_file: Optional[str] = None,
) -> dict[str, Any]:
    """提取 PDF 组分表信息并落盘到 JSON 文件。

    【职责】
    解析组分表 PDF。提取完成后弹出审核 UI，用户审核通过后落盘最终聚合结果。

    【使用场景】
    何时调用:
    - 需要从工艺组分表 PDF 获取组分清单（components）与物流组成（streams）时。
    - 需要跨多页组分表聚合去重，形成全厂统一组分/流股视图时。
    - 后续物料平衡、流程仿真需要组分基础数据时。

    何时不调用:
    - 输入文件不是 PDF（如已是图片）→ 本工具仅接受 PDF 路径。

    【参数说明】
    Args:
        pdf_path: 组分表 PDF 的绝对或相对路径，必须存在且为 .pdf 文件。
        start_page: 起始页码（0-based，含），默认 0。范围 [0, 总页数)。
        end_page: 结束页码（0-based，不含），None 表示到最后一页；
            传入时必须 > start_page，否则 ValueError。
        dpi: PDF 转图片的渲染 DPI，默认 300。建议范围 [150, 600]：
            过低会丢失表格小字，过高会增加 VLM 调用耗时与显存占用。
        output_file: 最终合并 JSON 的完整文件路径；None 时使用默认名
            ``工艺组分表相关信息.json``。
            需稳定路径请显式传入。文件内含 pages（逐页）+ aggregated +
            image_paths + reviewed_data 等全部产物。

    【返回结果】
    Returns:
        dict[str, Any]，关键字段：
        - status: "success" | "partial" | "failed"。
          （partial 表示有警告但全部页成功；failed 表示有页失败。）
        - workflow: "composition_table"。
        - output_file: 落盘的 JSON 文件完整路径（审核通过后才有）。
        - page_count: 实际提取的页数。
        - component_count: 聚合后组分总数。
        - stream_count: 聚合后物流总数。
        - image_paths: 各页渲染图片路径列表。
        - warnings: 警告信息列表（部分页失败会聚合到此处）。
        - errors: 失败时的错误明细（仅 status=failed 时存在）。

    【错误情况】
        返回 status="failed" 时 errors 字段含失败原因，常见情况：
        - PDF 文件不存在/路径错误（FileNotFoundError）。
        - PDF 渲染失败、页码越界（ValueError/RuntimeError）。
        - VLM API 调用失败、网络异常（httpx.HTTPError）。
        - 工作流内部提取失败（PFDAnalysisError），errors 含具体页码。
        - 审核驳回/超时（RuntimeError/TimeoutError），不落盘直接返回 failed。
        部分页失败时仍保存已成功页数据供上游取回（status=failed 但带 output_file）。
        所有页成功但有警告时返回 status="partial"，仍正常落盘。
    """
    await ctx.info(f"composition_table start: {pdf_path} (pages {start_page}..{end_page})")
    content = MCPContent(ctx, asyncio.get_running_loop())
    cancel_event = threading.Event()

    def _run_multi_page() -> dict[str, Any]:
        # PDF -> 图片（工作流内部只接受图片输入）
        image_paths = pdf_to_images_range(
            pdf_path,
            start_page=start_page,
            end_page=end_page,
            dpi=dpi,
            work_dir=None,
            host_client=get_host_client(),
        )
        workflow = CompositionTableWorkflow(
            settings=get_settings(),
            content=content,
            host_client=get_host_client(),
        )
        page_results = []
        all_warnings: list[str] = []
        total_pages = len(image_paths)
        partial_error: str | None = None
        cancelled = False
        for idx, img_path in enumerate(image_paths):
            if cancel_event.is_set():
                partial_error = f"客户端取消（已完成 {idx}/{total_pages} 页）"
                cancelled = True
                break
            try:
                page_result = workflow.analyze(
                    image_path=img_path,
                    page_index=start_page + idx,
                    cancel_event=cancel_event,
                )
            except PFDAnalysisError as e:
                if cancel_event.is_set():
                    partial_error = f"客户端取消（已完成 {idx}/{total_pages} 页）"
                    cancelled = True
                    break
                logger.error(f"composition_table: page {idx} extraction failed: {e}")
                partial_error = f"第 {idx + 1} 页提取失败: {e}"
                break
            page_results.append(page_result)
            all_warnings.extend(page_result.get("warnings", []))
            content.send_progress_with_data(
                progress=idx + 1,
                total=total_pages,
                message=f"第 {idx + 1}/{total_pages} 页提取完成",
            )

        aggregated = CompositionTableWorkflow.aggregate(page_results)
        if partial_error:
            all_warnings.append(partial_error)
        if not partial_error:
            content.send_progress_with_data(
                total_pages,
                total=total_pages,
                message="Composition table extraction completed",
                ui_event={
                    "event_type": "aggregation_complete",
                    "component_count": len(aggregated["components"]),
                    "stream_count": len(aggregated["streams"]),
                    "partial_aggregated": aggregated,
                },
            )
        final_result = {
            # partial_error 走 failed；取消走 cancelled；有 warnings 但全部成功 → partial（既有语义）
            "status": "cancelled" if cancelled else ("failed" if partial_error else ("partial" if all_warnings else "success")),
            "aggregated": aggregated,
            "image_paths": image_paths,
            "warnings": all_warnings,
            "pages": page_results,
        }
        return final_result

    try:
        result = await asyncio.to_thread(_run_multi_page)
    except asyncio.CancelledError:
        cancel_event.set()
        logger.info("composition_table: 客户端取消执行")
        raise
    except (FileNotFoundError, ValueError, RuntimeError, TypeError, httpx.HTTPError) as e:
        logger.error(f"composition_table: 输入准备失败（PDF 渲染/文件服务）: {e}")
        return {
            "status": "failed",
            "workflow": "composition_table",
            "errors": [str(e)],
            "warnings": [],
        }
    if result.get("status") in ("failed", "cancelled"):
        # 部分页失败/取消：仍保存已成功页数据供上游取回，返回 failed/cancelled + 文件地址（不进审核）
        return await asyncio.to_thread(
            _build_tool_output,
            "composition_table",
            result,
            output_file,
            {
                "version": "1.0.0",
                "workflow": "composition_table",
                "aggregated": result.get("aggregated", {}),
                "pages": result.get("pages", []),
                "image_paths": result.get("image_paths", []),
                "warnings": result.get("warnings", []),
            },
            meta={
                "page_count": len(result.get("image_paths", [])),
                "image_paths": result.get("image_paths", []),
                "warnings": result.get("warnings", []),
            },
        )
    try:
        # 语义 B：审核通过前不落盘；await_user_review 返回审核后的结果（edited_data 或 result）
        reviewed = await await_user_review(
            content,
            tool_name="composition_table",
            result=result,
            progress=float(len(result.get("image_paths", []))),
            total=float(len(result.get("image_paths", []))),
        )
    except (RuntimeError, TimeoutError) as e:
        # 审核驳回/超时：不落盘
        logger.error(f"composition_table: 审核链路失败，不落盘: {e}")
        return {
            "status": "failed",
            "workflow": "composition_table",
            "errors": [str(e)],
            "warnings": [],
        }
    return await asyncio.to_thread(
        _build_tool_output,
        "composition_table",
        result,
        output_file,
        # 合并后的单文件数据：pages（逐页结果列表）+ aggregated + image_paths + reviewed_data
        {
            "version": "1.0.0",
            "workflow": "composition_table",
            "aggregated": result.get("aggregated", {}),
            "pages": result.get("pages", []),
            "image_paths": result.get("image_paths", []),
            "warnings": result.get("warnings", []),
            "reviewed_data": reviewed,
        },
        meta={
            "page_count": len(result.get("image_paths", [])),
            "component_count": len(result.get("aggregated", {}).get("components", [])),
            "stream_count": len(result.get("aggregated", {}).get("streams", [])),
            "image_paths": result.get("image_paths", []),
            "warnings": result.get("warnings", []),
        },
    )


# ---------------------------------------------------------------------------
# Tool 8: demo_progress（演示/验证进度推送链路，无需 PDF 与 VLM）
# ---------------------------------------------------------------------------
async def demo_progress(
    ctx: Context,
    steps: int = 5,
    delay_ms: int = 500,
    message: str = "处理中",
) -> dict[str, Any]:
    """逐步推送 MCP 进度通知的演示工具，用于验证前端进度条（mcpProgress）渲染。

    【职责】
    按 ``steps`` 步循环，每步通过标准 ``notifications/progress`` 推送
    ``progress`` / ``total`` / ``message``；后端把进度映射到运行中工具 part 的
    ``metadata.mcpProgress``，前端时间线工具卡据此渲染进度条。

    【使用场景】
    何时调用:
    - 需要验证/演示 MCP 进度推送链路（MCP server -> 后端 -> 前端进度条）时。
    - 不依赖 PDF 与 VLM，可独立、确定性执行。

    何时不调用:
    - 任何真实图纸分析任务（请调用 pfd_topology 等业务工具）。

    【参数说明】
    Args:
        steps: 进度步数，默认 5。范围 [1, 20]。
        delay_ms: 每步间隔毫秒，默认 500。范围 [10, 5000]。
        message: 进度消息前缀，默认 "处理中"。最终显示为 ``<message> i/steps``。

    【返回结果】
    Returns:
        dict[str, Any]，含 status / workflow / steps / message。
    """
    await ctx.info(f"demo_progress start: steps={steps}, delay_ms={delay_ms}")
    steps = max(1, min(int(steps), 20))
    delay_ms = max(10, min(int(delay_ms), 5000))
    for step in range(1, steps + 1):
        await ctx.report_progress(
            progress=float(step),
            total=float(steps),
            message=f"{message} {step}/{steps}",
        )
        if step < steps:
            await asyncio.sleep(delay_ms / 1000.0)
    return {
        "status": "success",
        "workflow": "demo_progress",
        "steps": steps,
        "message": message,
        "note": "演示工具：进度推送完成",
    }


# ---------------------------------------------------------------------------
# Tool 9: read_image（app-only，供 UI 读取图片做背景图）
# ---------------------------------------------------------------------------
_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}


def _read_image_work_dir(pdf_path: Path) -> Path:
    """按 PDF 路径哈希返回稳定的缓存目录，避免每次调用新建临时目录。

    同一 PDF 反复渲染时复用同一目录，避免 ``mkdtemp`` 累积未清理的临时目录。
    """
    key = hashlib.md5(str(pdf_path).encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / f"mcp_read_image_{key}"


async def read_image(
    ctx: Context,
    path: str,
    page_index: Optional[int] = None,
    dpi: int = 300,
) -> dict[str, Any]:
    """读取本地图片文件并返回 base64 编码数据，供 UI 展示为拓扑编辑器背景图。

    本工具仅对 app 可见（visibility=["app"]），模型不会看到。
    UI 通过 ``tools/call`` 反向调用，将返回的 ``data_base64`` 拼成
    ``data:{mime_type};base64,{data_base64}`` 作为 ``<img>`` 或 canvas 背景。

    Args:
        path: 图片文件路径，或 PDF 文件路径（需配合 page_index）。
        page_index: 若 path 为 PDF，渲染该页（0-based）为 PNG 返回。
            None 时按普通图片文件处理。
        dpi: PDF 转图片的渲染 DPI（仅 page_index 非 None 或 path 为 PDF 时生效），默认 300。
    """
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = Path.cwd() / file_path

    client = get_host_client()

    # PDF 分支：渲染指定页为 PNG（PDF 经 HostClient.get_file 拉取到本地）
    if file_path.suffix.lower() == ".pdf":
        img_path = await asyncio.to_thread(
            pdf_first_page_to_image,
            file_path,
            page_index=page_index or 0,
            dpi=dpi,
            work_dir=_read_image_work_dir(file_path),
            host_client=client,
        )
        file_path = Path(img_path)

    mime = _IMAGE_MIME.get(file_path.suffix.lower(), "application/octet-stream")
    # 图片均为本地渲染产物（豁免 #5，本地文件读取），直接本地读取，不再经 HostClient
    data = await asyncio.to_thread(file_path.read_bytes)
    await ctx.info(f"read_image: {file_path.name} ({len(data)} bytes, {mime})")
    return {
        "mime_type": mime,
        "data_base64": base64.b64encode(data).decode("ascii"),
    }


async def read_pdf(
    ctx: Context,
    path: str,
) -> dict[str, Any]:
    """读取 PDF 文件并返回 base64 数据，供 UI 直接加载渲染整份 PDF 内容。

    本工具仅对 app 可见（visibility=["app"]），模型不会看到。
    UI 通过 ``tools/call`` 反向调用，把返回的 ``data_base64`` 拼成
    ``data:application/pdf;base64,{data_base64}`` 作为 iframe/object 的 src。

    Args:
        path: PDF 文件路径。本地已存在则直接读取（豁免本地文件读取）；
            否则经 ``host_client.get_file`` 以工作区相对逻辑路径拉取。
    """
    client = get_host_client()
    local = Path(path)
    if local.exists() and local.is_file():
        data = local.read_bytes()
    else:
        fetched = client.get_file(to_workspace_path(path))
        if not isinstance(fetched, (bytes, bytearray)):
            raise TypeError(
                f"read_pdf 期望 bytes，实际返回 {type(fetched).__name__}"
            )
        data = bytes(fetched)
    await ctx.info(f"read_pdf: {local.name} ({len(data)} bytes)")
    return {
        "mime_type": "application/pdf",
        "data_base64": base64.b64encode(data).decode("ascii"),
    }


# ---------------------------------------------------------------------------
# Tool 9: submit_review（app-only，供 UI 反向调用唤醒阻塞的审核工具）
# ---------------------------------------------------------------------------
async def submit_review(
    ctx: Context,
    review_id: str,
    approved: bool,
    edited_data: Optional[dict[str, Any]] = None,
    reason: str = "",
) -> dict[str, Any]:
    """UI 审核完成时反向调用，唤醒阻塞中的审核工具。

    本工具仅对 app 可见（visibility=["app"]），模型不会主动调用。
    UI 在用户点击"通过审核"/"驳回"时通过 ``tools/call`` 调用本工具，
    把审核结果回传给正在 ``await_user_review`` 中阻塞的审核工具
    （如 pfd_topology）。

    Args:
        review_id: 审核会话 id（由审核工具通过 progress.uiEvent.review_id 推送）。
        approved: 用户是否通过审核。
        edited_data: 用户编辑后的数据（approved=True 时必传）。
        reason: 驳回原因（approved=False 时必传）。
    """
    if not isinstance(approved, bool):
        raise ValueError("approved 必须为布尔值")
    registry = get_review_registry()
    ok = registry.resolve(
        review_id,
        {
            "approved": approved,
            "edited_data": edited_data,
            "reason": reason,
        },
    )
    if not ok:
        raise ValueError(f"无效或已过期的 review_id: {review_id}")
    await ctx.info(f"submit_review: review_id={review_id} approved={approved}")
    return {"status": "ok", "review_id": review_id, "approved": approved}


def register_tools(mcp: FastMCP) -> None:
    """将 tools 模块中的工具注册到给定的 FastMCP 实例。

    meta / timeout 在注册时绑定，函数本体保持为普通 async 函数，
    便于直接调用（如测试中 ``server.pfd_topology``）。

    timeout=7200（2 小时）：提取阶段可能耗时较长（多页 PDF + VLM 调用），
    审核等待（await_user_review）内部 timeout=3600s，工具级 timeout 必须
    大于「最大提取时间 + 审核超时」，否则提取时间挤占用户审核窗口。
    """
    mcp.tool(meta={"ui": {"resourceUri": PFD_TOPOLOGY_UI_URI}}, timeout=7200)(pfd_topology)
    mcp.tool(meta={"ui": {"resourceUri": PROCESS_PACKAGE_UI_URI}}, timeout=7200)(process_package)
    mcp.tool(meta={"ui": {"resourceUri": PLANT_UNIT_UI_URI}}, timeout=7200)(plant_unit_topology)
    mcp.tool(meta={"ui": {"resourceUri": EQUIPMENT_ASSEMBLY_UI_URI}}, timeout=7200)(equipment_assembly)
    mcp.tool(meta={"ui": {"resourceUri": PFD_REFLUX_UI_URI}}, timeout=7200)(pfd_reflux)
    mcp.tool(meta={"ui": {"resourceUri": COMPOSITION_TABLE_UI_URI}}, timeout=7200)(composition_table)
    mcp.tool()(demo_progress)
    mcp.tool(meta={"ui": {"visibility": ["app"]}})(read_image)
    mcp.tool(meta={"ui": {"visibility": ["app"]}})(read_pdf)
    mcp.tool(meta={"ui": {"visibility": ["app"]}})(submit_review)
