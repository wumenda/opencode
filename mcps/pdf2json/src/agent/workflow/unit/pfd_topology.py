"""PFD Topology Workflow.

Runs equipment + boundary_node + drawing_info experts in parallel to extract
nodes with bbox/position/ports and drawing metadata, injects a slim subset of
their fields into the topology expert's prompt as context (VLM only emits
edges), then merges the upstream nodes (with bbox/position/ports) directly onto
the topology output alongside the VLM-extracted edges.
"""

import copy
import json
import threading
from typing import Any, Optional

from src._internal import load_equipment_table, load_process_description
from src.agent.experts import (
    BoundaryNodeExpert,
    DrawingInfoExpert,
    EquipmentExpert,
    PFDTopologyExpert,
)
from src.agent.models import ExpertOutput, TopologyState
from duck.content import Content
from duck.host_client import HostClient
from src.core import Settings, get_logger
from src.core.infra.exceptions import CancelledByClientError, PFDAnalysisError

from ..core import BaseWorkflow

logger = get_logger(__name__)


class PFDTopologyWorkflow(BaseWorkflow):
    """Equipment + BoundaryNode + DrawingInfo parallel -> context-injected Topology -> bbox merge."""

    workflow_name = "pfd_topology"

    expert_output_keys: list[tuple[str, str]] = [
        ("equipment", "equipment_output"),
        ("boundary_node", "boundary_node_output"),
        ("drawing_info", "drawing_info_output"),
        ("topology", "topology_output"),
    ]

    def __init__(
        self,
        settings: Settings,
        max_workers: int = 2,
        process_description_path: Optional[str] = None,
        equipment_table_path: Optional[str] = None,
        content: Optional[Content] = None,
        host_client: Optional[HostClient] = None,
    ) -> None:
        self._content = content
        self._host_client = host_client

        self.process_description = ""
        if process_description_path:
            pdf_bytes = self._load_pdf_bytes(process_description_path)
            self.process_description = load_process_description(pdf_bytes)

        self._equipment_table = None
        if equipment_table_path:
            pdf_bytes = self._load_pdf_bytes(equipment_table_path)
            self._equipment_table = load_equipment_table(pdf_bytes)

        super().__init__(
            settings=settings,
            max_workers=max_workers,
            content=content,
            host_client=host_client,
        )

    def _init_experts(self) -> None:
        self.equipment_expert = EquipmentExpert(self.settings, self.process_description)
        self.boundary_node_expert = BoundaryNodeExpert(
            self.settings,
            self.process_description,
        )
        self.drawing_info_expert = DrawingInfoExpert(
            self.settings,
            self.process_description,
        )
        self.topology_expert = PFDTopologyExpert(self.settings, self.process_description)

    def _log_workflow_info(self) -> None:
        logger.info("=" * 60)
        logger.info("Workflow: PFDTopology")
        logger.info(f"Process description loaded: {len(self.process_description) > 0}")
        logger.info("-" * 60)
        logger.info("Prompt versions:")
        logger.info(f"  Equipment Expert: {self.equipment_expert._prompt_builder.version}")
        logger.info(f"  Boundary Node Expert: {self.boundary_node_expert._prompt_builder.version}")
        logger.info(f"  Drawing Info Expert: {self.drawing_info_expert._prompt_builder.version}")
        logger.info(f"  Topology Expert: {self.topology_expert._prompt_builder.version}")
        logger.info("-" * 60)
        logger.info(
            "Phase 1 (parallel): Equipment ∥ BoundaryNode ∥ DrawingInfo"
        )
        logger.info("Phase 2 (sequential): Topology with injected node context")
        logger.info("Phase 3 (merge): merge upstream nodes (with bbox) + VLM edges")
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # UI 增量推送辅助（与 mock_server 行为对齐）
    # ------------------------------------------------------------------

    def _get_image_info(self, image_path: str) -> dict[str, Any]:
        """读取图片宽高（供 UI 画布按真实宽高比渲染）。

        通过 _load_image 加载内存图像后读取尺寸，不直接使用本地文件 API。
        读取失败时回退到默认尺寸。
        """
        try:
            img = self._load_image(image_path)
            return {"path": image_path, "width": img.width, "height": img.height}
        except Exception:
            return {"path": image_path, "width": 4096, "height": 2897}

    def _build_partial_page_graph(
        self,
        state: TopologyState,
        page_index: int,
        equipment_nodes: list[dict[str, Any]] | None = None,
        boundary_nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
        drawing_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构造单页 page_graph，供 partial_page_graphs 推送给 UI 逐步渲染。

        结构与 mock_server._build_page_graph 对齐：pfd_drawing.topology 含
        equipment_nodes / boundary_nodes / edges 三段，前端 parsePfdDrawing
        据此分流渲染节点与边。
        """
        image_path = state.image_path
        return {
            "page_index": page_index,
            "page_label": f"第 {page_index + 1} 页",
            "pfd_drawing": {
                "page_index": page_index,
                "image_path": image_path,
                "image_info": self._get_image_info(image_path),
                "drawing_info": drawing_info or {"drawing_type": "PFD"},
                "topology": {
                    "equipment_nodes": equipment_nodes or [],
                    "boundary_nodes": boundary_nodes or [],
                    "edges": edges or [],
                },
            },
        }

    @staticmethod
    def _extract_list(output: "ExpertOutput | None", key: str) -> list[dict[str, Any]]:
        """从 ExpertOutput.data[key] 安全取 list，失败返回空 list。"""
        if output and output.success and output.data:
            v = output.data.get(key)
            if isinstance(v, list):
                return v
        return []

    @staticmethod
    def _extract_edges_from_topology(topology_result: "ExpertOutput") -> list[dict[str, Any]]:
        """从 topology ExpertOutput.data.topology.edges 取边列表。"""
        if not (topology_result.success and topology_result.data):
            return []
        topo = topology_result.data.get("topology", topology_result.data)
        if isinstance(topo, dict):
            edges = topo.get("edges", [])
            if isinstance(edges, list):
                return edges
        return []

    @staticmethod
    def _extract_drawing_info_dict(state: TopologyState) -> dict[str, Any]:
        """从 drawing_info_output.data.drawing_info 取图纸元信息 dict。"""
        out = state.extraction.drawing_info_output
        if out and out.success and out.data:
            di = out.data.get("drawing_info")
            if isinstance(di, dict):
                return di
        return {"drawing_type": "PFD"}

    def _phase_progress(self, phase: float) -> float:
        """把单页内的阶段值换算成全局进度点。

        多页运行时通过 ``progress_offset_phases`` 把每页的阶段平移到
        ``[page*5, (page+1)*5]`` 区间（total 恒为 ``progress_total_phases``），
        使进度在跨页间连续递增、不再回退到 0。
        """
        return self._progress_offset + phase

    def analyze(
        self,
        image_path: str,
        page_index: int = 0,
        progress_offset_phases: float = 0.0,
        progress_total_phases: float = 5.0,
        cancel_event: Optional[threading.Event] = None,
    ) -> dict[str, Any]:
        self._cancel_event = cancel_event
        logger.info("=" * 80)
        logger.info("Workflow: PFDTopology started")
        logger.info(f"Input: {image_path}")
        logger.info("=" * 80)

        # 进度全局刻度：多页时每页只占 1/N 段，page offset 续接避免跨页重置
        self._progress_offset = progress_offset_phases
        self._progress_total = progress_total_phases

        # 阶段 0：推送 image_paths + image_infos，UI 立即加载底图
        self._content.send_progress_with_data(
            self._phase_progress(0), total=self._progress_total, message="Starting PFD topology extraction",
            ui_event={
                "event_type": "image_loaded",
                "page_index": page_index,
                "image_paths": [image_path],
                "image_infos": [self._get_image_info(image_path)],
            },
        )

        # 通过 HostClient 加载图片为内存 Image（不触碰本地文件 API）
        loaded_image = self._load_image(image_path) if self._host_client else None
        image_path = self._resolve_input_path(image_path)
        state = TopologyState(image_path=image_path)

        try:
            self._run_extraction_stages(state, loaded_image)
            if self._cancel_event and self._cancel_event.is_set():
                raise CancelledByClientError("客户端取消（extraction 阶段后）")
            # 阶段 1：equipment + boundary 已就绪，无 edges
            pg1 = self._build_partial_page_graph(
                state, page_index,
                equipment_nodes=self._extract_list(state.extraction.equipment_output, "equipment"),
                boundary_nodes=self._extract_list(state.extraction.boundary_node_output, "boundary_node"),
                edges=[],
                drawing_info=self._extract_drawing_info_dict(state),
            )
            self._content.send_progress_with_data(
                self._phase_progress(1), total=self._progress_total, message="Extraction experts completed",
                ui_event={
                    "event_type": "nodes_extracted",
                    "page_index": page_index,
                    "partial_page_graphs": [pg1],
                },
            )

            topology_result = self._run_topology_with_context(state, image_path, loaded_image)
            state.extraction.topology_output = topology_result
            if self._cancel_event and self._cancel_event.is_set():
                raise CancelledByClientError("客户端取消（topology 阶段后）")
            # 阶段 2：拓扑边已就绪
            edges2 = self._extract_edges_from_topology(topology_result)
            pg2 = self._build_partial_page_graph(
                state, page_index,
                equipment_nodes=self._extract_list(state.extraction.equipment_output, "equipment"),
                boundary_nodes=self._extract_list(state.extraction.boundary_node_output, "boundary_node"),
                edges=edges2,
                drawing_info=self._extract_drawing_info_dict(state),
            )
            self._content.send_progress_with_data(
                self._phase_progress(2), total=self._progress_total, message="Topology extraction completed",
                ui_event={
                    "event_type": "topology_extracted",
                    "page_index": page_index,
                    "partial_page_graphs": [pg2],
                },
            )

            merged_topology = self._merge_bbox_into_topology(state, topology_result)
            if self._cancel_event and self._cancel_event.is_set():
                raise CancelledByClientError("客户端取消（merge 阶段后）")
            # 阶段 3：合并后节点（含 bbox）
            pg3 = self._build_partial_page_graph(
                state, page_index,
                equipment_nodes=merged_topology.get("equipment_nodes", []),
                boundary_nodes=merged_topology.get("boundary_nodes", []),
                edges=merged_topology.get("edges", []),
                drawing_info=self._extract_drawing_info_dict(state),
            )
            self._content.send_progress_with_data(
                self._phase_progress(3), total=self._progress_total, message="Node merge completed",
                ui_event={
                    "event_type": "nodes_merged",
                    "page_index": page_index,
                    "partial_page_graphs": [pg3],
                },
            )

            self._run_post_validation(state, merged_topology)
            if self._cancel_event and self._cancel_event.is_set():
                raise CancelledByClientError("客户端取消（validation 阶段后）")
            # 阶段 4：校验结果
            validation_result = (
                state.validation.validation_result.model_dump()
                if state.validation.validation_result else None
            )
            self._content.send_progress_with_data(
                self._phase_progress(4), total=self._progress_total, message="Validation completed",
                ui_event={
                    "event_type": "validation_ready",
                    "page_index": page_index,
                    "validation": validation_result,
                },
            )

            self._content.send_progress_with_data(
                self._phase_progress(5), total=self._progress_total, message="Analysis completed successfully")
            logger.info("=" * 80)
            logger.info("Analysis completed successfully")
            logger.info("=" * 80)

            return self._build_final_output(state, merged_topology)

        except PFDAnalysisError:
            raise
        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            raise PFDAnalysisError(f"Workflow {self.workflow_name} failed: {e}") from e

    # ------------------------------------------------------------------
    # Phase 1: 提取阶段并行调度（equipment / boundary_node / drawing_info）
    # ------------------------------------------------------------------

    def _run_extraction_stages(self, state: TopologyState, loaded_image=None) -> None:
        """并行调度提取阶段：equipment ∥ boundary_node ∥ drawing_info。

        三个专家互不依赖，由 ``self.max_workers`` 统一控制并行度：
            - ``max_workers <= 1``：串行执行（drawing_info -> equipment -> boundary_node）
            - ``max_workers > 1``：ThreadPoolExecutor 并行，as_completed 收集结果

        drawing_info 仅在子类初始化了 ``self.drawing_info_expert`` 时加入调度。
        它是辅助元信息提取，失败降级为 warning，不中断主流程；equipment /
        boundary_node 失败保持 fail-fast，取消未开始的任务后抛出。
        """
        image_path = state.composition.main_area_image_path or state.image_path

        self.logger.info("Step 1: Running extraction experts...")
        self._content.send_progress_with_data(
            self._phase_progress(0.5), total=self._progress_total,
            message="Running extraction experts (equipment/boundary/drawing_info)",
        )
        self.logger.info(
            f"  Equipment prompt version: {self.equipment_expert._prompt_builder.version}"
        )
        self.logger.info(
            f"  Boundary node prompt version: {self.boundary_node_expert._prompt_builder.version}"
        )
        has_drawing_info = getattr(self, "drawing_info_expert", None) is not None
        if has_drawing_info:
            self.logger.info(
                f"  Drawing info prompt version: {self.drawing_info_expert._prompt_builder.version}"
            )
        self.logger.info(
            f"  max_workers: {self.max_workers} "
            f"({'并行' if self.max_workers > 1 else '串行'})"
        )

        # 构建提取任务表：(阶段名, 可调用对象)
        stage_tasks: list[tuple[str, Any]] = []
        if has_drawing_info:
            stage_tasks.append(
                ("drawing_info", lambda: self._extract_drawing_info(state, image_path, loaded_image))
            )
        stage_tasks.append(
            ("equipment", lambda: self._extract_equipment(state, image_path, loaded_image))
        )
        stage_tasks.append(
            ("boundary_node", lambda: self._extract_boundary_node(state, image_path, loaded_image))
        )

        if self.max_workers <= 1:
            # 串行：按 stage_tasks 顺序执行；drawing_info 失败降级为 warning
            for stage_name, fn in stage_tasks:
                self._invoke_extraction_stage(stage_name, fn, state)
            return

        # 并行：ThreadPoolExecutor + as_completed
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_name: dict = {
                executor.submit(fn): name for name, fn in stage_tasks
            }
            for future in as_completed(future_to_name):
                stage_name = future_to_name[future]
                try:
                    future.result()
                    self._log_stage_completion(stage_name, state)
                except Exception as e:
                    if stage_name == "drawing_info":
                        # drawing_info 是辅助元信息，失败降级为警告
                        self.logger.error(f"drawing_info expert failed: {e}")
                        state.warnings.append(f"drawing_info expert failed: {e}")
                        self._ensure_drawing_info_failure_output(state, e)
                        continue
                    self.logger.error(f"{stage_name} expert failed: {e}")
                    for f in future_to_name:
                        if not f.done():
                            f.cancel()
                    raise PFDAnalysisError(f"{stage_name} expert failed: {e}") from e

    def _invoke_extraction_stage(
        self, stage_name: str, fn: Any, state: TopologyState
    ) -> None:
        """串行模式下执行单个提取阶段，处理 drawing_info 的降级策略。"""
        try:
            fn()
        except Exception as e:
            if stage_name == "drawing_info":
                self.logger.error(f"drawing_info expert failed: {e}")
                state.warnings.append(f"drawing_info expert failed: {e}")
                self._ensure_drawing_info_failure_output(state, e)
                return
            raise
        self._log_stage_completion(stage_name, state)

    def _log_stage_completion(self, stage_name: str, state: TopologyState) -> None:
        if stage_name == "equipment":
            ok = bool(
                state.extraction.equipment_output
                and state.extraction.equipment_output.success
            )
            self.logger.info(f"equipment expert completed: {ok}")
        elif stage_name == "boundary_node":
            ok = bool(
                state.extraction.boundary_node_output
                and state.extraction.boundary_node_output.success
            )
            self.logger.info(f"boundary_node stage completed: {ok}")
        elif stage_name == "drawing_info":
            ok = bool(
                state.extraction.drawing_info_output
                and state.extraction.drawing_info_output.success
            )
            self.logger.info(f"drawing_info expert completed: {ok}")

    def _extract_equipment(
        self,
        state: TopologyState,
        image_path: str,
        loaded_image=None,
    ) -> None:
        """执行 equipment expert 并写入 state。"""
        from src.agent.models import ImageMetadata

        result = self.equipment_expert.analyze(image_path, loaded_image=loaded_image, cancel_event=self._cancel_event)
        state.extraction.equipment_output = result

        if result.image_metadata and not state.image_metadata:
            state.image_metadata = ImageMetadata(**result.image_metadata)

    def _extract_boundary_node(
        self,
        state: TopologyState,
        image_path: str,
        loaded_image=None,
    ) -> None:
        """执行 boundary_node expert 并写入 state。"""
        self.logger.info("Running boundary_node expert...")
        result = self.boundary_node_expert.analyze(image_path, loaded_image=loaded_image, cancel_event=self._cancel_event)
        state.extraction.boundary_node_output = result

        self.logger.info(f"boundary_node expert completed: {result.success}")

    def _extract_drawing_info(self, state: TopologyState, image_path: str, loaded_image=None) -> None:
        """执行 drawing_info expert 并写入 state。

        仅在子类初始化了 ``self.drawing_info_expert`` 时被调度。失败由上层
        （串行/并行分支）统一按辅助阶段降级处理。
        """
        from src.agent.models import ImageMetadata

        result = self.drawing_info_expert.analyze(image_path, loaded_image=loaded_image, cancel_event=self._cancel_event)
        state.extraction.drawing_info_output = result

        if result.image_metadata and not state.image_metadata:
            state.image_metadata = ImageMetadata(**result.image_metadata)

    def _ensure_drawing_info_failure_output(
        self, state: TopologyState, error: Exception
    ) -> None:
        """drawing_info 失败时写入占位 ExpertOutput，保持下游读取一致。"""
        from src.agent.models import ExpertOutput

        if state.extraction.drawing_info_output is None:
            state.extraction.drawing_info_output = ExpertOutput(
                expert_type="drawing_info",
                success=False,
                errors=[str(error)],
            )

    # ------------------------------------------------------------------
    # Phase 2: Topology with injected context
    # ------------------------------------------------------------------

    def _run_topology_with_context(
        self, state: TopologyState, image_path: str, loaded_image=None
    ) -> ExpertOutput:
        self.logger.info("Step 2: Running topology expert with injected node context...")
        self._content.send_progress_with_data(
            self._phase_progress(1.5), total=self._progress_total,
            message="Running topology expert with injected context",
        )
        self.logger.info(
            f"  Topology prompt version: {self.topology_expert._prompt_builder.version}"
        )

        context = self._build_pfd_topology_context(state)
        result = self.topology_expert.analyze(image_path, context, loaded_image=loaded_image, cancel_event=self._cancel_event)

        self.logger.info(f"Topology expert completed: {result.success}")
        return result

    def _build_pfd_topology_context(self, state: TopologyState) -> dict[str, Any]:
        context: dict[str, Any] = {}
        if (
            state.extraction.equipment_output
            and state.extraction.equipment_output.success
            and state.extraction.equipment_output.data
        ):
            equipment = state.extraction.equipment_output.data.get("equipment", [])
            if isinstance(equipment, list):
                context["equipment"] = equipment
        if (
            state.extraction.boundary_node_output
            and state.extraction.boundary_node_output.success
            and state.extraction.boundary_node_output.data
        ):
            boundary_node = state.extraction.boundary_node_output.data.get(
                "boundary_node", []
            )
            if isinstance(boundary_node, list):
                context["boundary_node"] = boundary_node
        if (
            state.extraction.drawing_info_output
            and state.extraction.drawing_info_output.success
            and state.extraction.drawing_info_output.data
        ):
            drawing_info = state.extraction.drawing_info_output.data.get("drawing_info")
            if isinstance(drawing_info, dict) and drawing_info:
                context["drawing_info"] = drawing_info
        return context

    # ------------------------------------------------------------------
    # Phase 3: Merge upstream nodes + VLM edges
    # ------------------------------------------------------------------

    def _merge_bbox_into_topology(
        self, state: TopologyState, topology_result: ExpertOutput
    ) -> dict[str, Any]:
        """直接合并上游节点（含 bbox/position/ports）与 VLM 提取的 edges。

        pfd_topology 提示词下 VLM 只输出 edges，equipment_nodes / boundary_nodes
        与上游传入完全一致，因此无需回填--直接将上游节点（含 bbox）作为拓扑节点，
        与 VLM 输出的 edges 合并即可。边端点 id 对齐到上游官方 id；boundary 节点
        方向若与 edges 实际角色冲突，按 edges 投票自动修正 boundary_type。
        """
        if not (topology_result.success and topology_result.data):
            return topology_result.data if topology_result.data else {}

        raw_data = json.loads(json.dumps(topology_result.data, ensure_ascii=False))
        topology_data = raw_data.get("topology", raw_data)

        equipment_by_id = self._index_equipment_by_id(state)
        boundary_by_id = self._index_boundary_by_id(state)

        # Step 1: 把 VLM 输出的边端点 id 对齐到上游官方 id（宽松匹配大小写/空白）
        self._remap_topology_ids_to_upstream(
            topology_data, equipment_by_id, boundary_by_id
        )

        # Step 2: 直接合并上游节点（含 bbox/position/ports）作为拓扑节点
        topology_data["equipment_nodes"] = copy.deepcopy(list(equipment_by_id.values()))
        topology_data["boundary_nodes"] = copy.deepcopy(list(boundary_by_id.values()))

        # Step 3: 根据 edges 角色投票修正 boundary 方向，并同步回上游 state
        self._correct_boundary_directions(state, topology_data, boundary_by_id)

        self.logger.info(
            f"Node merge: {len(topology_data['equipment_nodes'])} equipment nodes, "
            f"{len(topology_data['boundary_nodes'])} boundary nodes from upstream; "
            f"{len(topology_data.get('edges', []))} edges from VLM"
        )
        return topology_data

    def _run_post_validation(
        self, state: TopologyState, merged_topology: dict[str, Any]
    ) -> None:
        """对合并后的拓扑运行图结构 + 端口约束后校验，结果写入 state.validation。"""
        from src.agent.validation.topology_validator import run_post_validation

        run_post_validation(state, merged_topology, self.settings.validation)
        vr = state.validation.validation_result
        if vr is not None:
            self.logger.info(
                f"Post-validation: status={vr.validation_status}, "
                f"issues={len(vr.issues)}, needs_human_review={len(vr.needs_human_review)}"
            )

    @staticmethod
    def _canonical_id(value: Any) -> str:
        """归一化 id：去空白 + 小写，用于宽松匹配。"""
        return str(value or "").strip().lower()

    def _remap_topology_ids_to_upstream(
        self,
        topology_data: dict[str, Any],
        equipment_by_id: dict[str, dict[str, Any]],
        boundary_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """把 topology 输出中的 id 统一回写为上游官方 id（处理大小写/空白漂移）。

        典型场景：上游 equipment_output 中 id='equip_1'，VLM 输出 topology 时
        写成 'Equip_1' 或 ' equip_1 '；如果直接按字符串匹配，bbox 合并会全部
        miss，最终前端定位/校验全错。

        本方法构建 canonical_id -> upstream_official_id 的映射，将
        topology_data 中所有节点 id 与 edges 的 source/target 统一改写为上游
        官方 id；找不到映射时保留原值（便于 _validate_edge 与日志报警）。
        """
        canonical_to_official: dict[str, str] = {}
        for upstream_id in list(equipment_by_id.keys()) + list(boundary_by_id.keys()):
            canonical_to_official.setdefault(self._canonical_id(upstream_id), upstream_id)

        if not canonical_to_official:
            return

        remapped_nodes = 0
        for node in (
            topology_data.get("equipment_nodes", [])
            + topology_data.get("boundary_nodes", [])
        ):
            if not isinstance(node, dict):
                continue
            raw = str(node.get("id", ""))
            official = canonical_to_official.get(self._canonical_id(raw))
            if official and official != raw:
                node["id"] = official
                remapped_nodes += 1
            elif raw != raw.strip():
                node["id"] = raw.strip()

        remapped_edges = 0
        for edge in topology_data.get("edges", []):
            if not isinstance(edge, dict):
                continue
            for field in ("source_node_id", "target_node_id"):
                raw = edge.get(field, "")
                if not isinstance(raw, str):
                    continue
                official = canonical_to_official.get(self._canonical_id(raw))
                if official and official != raw:
                    edge[field] = official
                    remapped_edges += 1
                elif raw != raw.strip():
                    edge[field] = raw.strip()

        if remapped_nodes or remapped_edges:
            self.logger.info(
                f"Topology id remap: {remapped_nodes} node(s), "
                f"{remapped_edges} edge endpoint(s) aligned to upstream ids"
            )

    def _correct_boundary_directions(
        self,
        state: TopologyState,
        topology_data: dict[str, Any],
        upstream_boundary_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """依据 edges 角色投票修正 boundary 节点的 boundary_type。

        问题背景：boundary_node expert 偶尔会将进料/出料方向标反（如把
        cross_drawing_in 标成 cross_drawing_out），导致 prompt 硬约束
        "boundary_out 不能作为 source" 命中后，topology expert 不敢输出
        该节点的边，整条拓扑断裂。

        本方法用 edges 中实际可见的角色作为更可信的证据：若一个 boundary
        节点仅作为 source 出现，则它实际是 *_in；仅作为 target 出现则是 *_out。
        与 prompt 约束冲突时按 edges 修正，并同步回 state.boundary_node_output，
        让最终输出/可视化方向一致。

        混合角色（既 source 又 target）通常代表 VLM 误连或节点本身有问题，
        此时保留原值并打 warning，由人工审核。
        """
        edges = topology_data.get("edges", []) or []
        topo_bnd_nodes = topology_data.get("boundary_nodes", []) or []
        if not edges or not topo_bnd_nodes:
            return

        bnd_id_set = {
            str(b.get("id", "")).strip() for b in topo_bnd_nodes if isinstance(b, dict)
        }
        bnd_id_set.discard("")

        source_count: dict[str, int] = {}
        target_count: dict[str, int] = {}
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            src = str(edge.get("source_node_id", "")).strip()
            tgt = str(edge.get("target_node_id", "")).strip()
            if src in bnd_id_set:
                source_count[src] = source_count.get(src, 0) + 1
            if tgt in bnd_id_set:
                target_count[tgt] = target_count.get(tgt, 0) + 1

        # 构造 topology boundary_nodes 索引（按 id），便于回写 boundary_type
        topo_bnd_by_id = {
            str(b.get("id", "")).strip(): b
            for b in topo_bnd_nodes
            if isinstance(b, dict) and b.get("id")
        }

        # 同步回上游 boundary_node_output.data["boundary_node"] 列表
        upstream_list: list[dict[str, Any]] = []
        boundary_output = state.extraction.boundary_node_output
        if (
            boundary_output
            and boundary_output.success
            and boundary_output.data
            and isinstance(boundary_output.data.get("boundary_node"), list)
        ):
            upstream_list = boundary_output.data["boundary_node"]
        upstream_by_id = {
            str(b.get("id", "")).strip(): b
            for b in upstream_list
            if isinstance(b, dict) and b.get("id")
        }

        fixed: list[tuple[str, str, str]] = []
        ambiguous: list[str] = []
        for bnd_id in bnd_id_set:
            sc = source_count.get(bnd_id, 0)
            tc = target_count.get(bnd_id, 0)
            if sc == 0 and tc == 0:
                continue

            # 取上游/topology 中的现有 boundary_type 作为基准
            current_type = ""
            upstream_bn = upstream_by_id.get(bnd_id) or upstream_boundary_by_id.get(bnd_id)
            if isinstance(upstream_bn, dict):
                current_type = str(upstream_bn.get("boundary_type", "")).strip()
            if not current_type:
                topo_bn = topo_bnd_by_id.get(bnd_id) or {}
                current_type = str(topo_bn.get("boundary_type", "")).strip()
            if not current_type:
                continue

            is_in_type = current_type in ("boundary_in", "cross_drawing_in")
            is_out_type = current_type in ("boundary_out", "cross_drawing_out")

            if sc > 0 and tc == 0 and is_out_type:
                # 实际作为 source 但被标为 out -> 翻转为 *_in
                new_type = (
                    "cross_drawing_in"
                    if current_type == "cross_drawing_out"
                    else "boundary_in"
                )
                self._apply_boundary_type(
                    bnd_id, new_type, topo_bnd_by_id, upstream_by_id, upstream_boundary_by_id
                )
                fixed.append((bnd_id, current_type, new_type))
            elif tc > 0 and sc == 0 and is_in_type:
                # 实际作为 target 但被标为 in -> 翻转为 *_out
                new_type = (
                    "cross_drawing_out"
                    if current_type == "cross_drawing_in"
                    else "boundary_out"
                )
                self._apply_boundary_type(
                    bnd_id, new_type, topo_bnd_by_id, upstream_by_id, upstream_boundary_by_id
                )
                fixed.append((bnd_id, current_type, new_type))
            elif sc > 0 and tc > 0:
                ambiguous.append(bnd_id)

        for bnd_id, old, new in fixed:
            msg = (
                f"Boundary direction auto-corrected by edge roles: '{bnd_id}' "
                f"{old} -> {new}"
            )
            self.logger.info(msg)
            state.warnings.append(msg)

        for bnd_id in ambiguous:
            msg = (
                f"Boundary node '{bnd_id}' appears as both edge source and target; "
                f"keep original boundary_type but please review"
            )
            self.logger.warning(msg)
            state.warnings.append(msg)

    @staticmethod
    def _apply_boundary_type(
        bnd_id: str,
        new_type: str,
        topo_bnd_by_id: dict[str, dict[str, Any]],
        upstream_by_id: dict[str, dict[str, Any]],
        upstream_boundary_by_id: dict[str, dict[str, Any]],
    ) -> None:
        """同步更新 topology 输出与上游 boundary_node_output 中的 boundary_type。"""
        topo_bn = topo_bnd_by_id.get(bnd_id)
        if isinstance(topo_bn, dict):
            topo_bn["boundary_type"] = new_type
        upstream_bn = upstream_by_id.get(bnd_id)
        if isinstance(upstream_bn, dict):
            upstream_bn["boundary_type"] = new_type
        idx_bn = upstream_boundary_by_id.get(bnd_id)
        if isinstance(idx_bn, dict):
            idx_bn["boundary_type"] = new_type

    def _index_equipment_by_id(self, state: TopologyState) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        if not (
            state.extraction.equipment_output
            and state.extraction.equipment_output.success
            and state.extraction.equipment_output.data
        ):
            return index
        for eq in state.extraction.equipment_output.data.get("equipment", []):
            if not isinstance(eq, dict):
                continue
            node_id = str(eq.get("id", "")).strip()
            if node_id and node_id not in index:
                index[node_id] = eq
        return index

    def _index_boundary_by_id(self, state: TopologyState) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        if not (
            state.extraction.boundary_node_output
            and state.extraction.boundary_node_output.success
            and state.extraction.boundary_node_output.data
        ):
            return index
        for bn in state.extraction.boundary_node_output.data.get("boundary_node", []):
            if not isinstance(bn, dict):
                continue
            node_id = str(bn.get("id", "")).strip()
            if node_id and node_id not in index:
                index[node_id] = bn
        return index

    # ------------------------------------------------------------------
    # Output construction
    # ------------------------------------------------------------------

    def _build_final_output(
        self, state: TopologyState, merged_topology: dict[str, Any]
    ) -> dict[str, Any]:
        expert_outputs = {}
        for output_key, state_attr in self.expert_output_keys:
            output = getattr(state.extraction, state_attr, None)
            expert_outputs[output_key] = output.model_dump() if output else None

        self._collect_workflow_warnings(state, expert_outputs)
        self._check_equipment_tags_against_table(state, merged_topology)

        drawing_info = self._extract_drawing_info_dict(state)
        pfd_drawing = self._build_pfd_drawing_from_topology(
            merged_topology, page_index=0, drawing_info=drawing_info
        )

        return {
            "version": "1.0.0",
            "workflow": self.workflow_name,
            "image_metadata": (
                state.image_metadata.model_dump() if state.image_metadata else None
            ),
            "status": "success" if not state.errors and not state.warnings else "partial",
            "pfd_drawing": pfd_drawing,
            "topology": merged_topology,
            "validation_result": (
                state.validation.validation_result.model_dump()
                if state.validation.validation_result
                else None
            ),
            "expert_outputs": expert_outputs,
            "errors": state.errors,
            "warnings": state.warnings,
        }

    @staticmethod
    def _extract_drawing_info_dict(state: TopologyState) -> Optional[dict[str, Any]]:
        """从 drawing_info_output 中提取 DrawingInfo 字典，供 build_pfd_drawing 使用。"""
        output = state.extraction.drawing_info_output
        if output and output.success and output.data:
            info = output.data.get("drawing_info")
            if isinstance(info, dict):
                return info
        return None

    def _collect_workflow_warnings(
        self, state: TopologyState, expert_outputs: dict[str, Any]
    ) -> None:
        """Surface expert-level parse failures into workflow warnings so the
        final status reflects partial results instead of a misleading success.
        """
        for expert_key in ("equipment", "boundary_node", "drawing_info", "topology"):
            output = getattr(state.extraction, f"{expert_key}_output", None)
            if not output:
                state.warnings.append(f"{expert_key} expert produced no output")
                continue
            if not output.success:
                state.warnings.append(f"{expert_key} expert reported failure")
            if output.warnings:
                for w in output.warnings:
                    state.warnings.append(f"{expert_key}: {w}")

        topo_data = (
            expert_outputs.get("topology", {}) or {}
        )
        topo = topo_data.get("data", {}).get("topology", {}) if isinstance(topo_data, dict) else {}
        edges = topo.get("edges", []) if isinstance(topo, dict) else []
        # pfd_topology 下 VLM 只输出 edges（节点由上游合并），仅当 edges 也为空时告警
        if not edges:
            state.warnings.append(
                "topology: empty edges result - "
                "likely JSON parse failure or reasoning consumed output tokens"
            )

    def _check_equipment_tags_against_table(
        self, state: TopologyState, merged_topology: dict[str, Any]
    ) -> None:
        """校验提取到的设备节点 tag 是否在用户提供的工艺设备表中。

        若不在，说明模型可能将设备 tag 识别错了，生成警告供前端审核时高亮该节点。
        警告格式约定：第一个单引号包裹的内容为 node_id，前端据此高亮节点。
        """
        if not self._equipment_table:
            return

        equipment_nodes = merged_topology.get("equipment_nodes", []) if merged_topology else []
        if not equipment_nodes:
            return

        from src.agent.validation.equipment_table_checker import (
            build_tag_warnings,
            check_equipment_tags,
        )

        results = check_equipment_tags(equipment_nodes, self._equipment_table)
        if results:
            warnings = build_tag_warnings(results)
            state.warnings.extend(warnings)
            self.logger.info(
                f"Equipment table tag check: {len(results)}/{len(equipment_nodes)} "
                f"equipment nodes not matched in table"
            )

    @staticmethod
    def _build_pfd_drawing_from_topology(
        merged_topology: dict[str, Any],
        page_index: int = 0,
        page_label: str = "",
        drawing_info: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Convert merged topology to a PFDDrawing model dict.

        Builds a PFDDrawing model instance from the merged topology, combining
        equipment_nodes + boundary_nodes into a single `nodes` list. The model
        is then serialized to dict to ensure the output conforms to the
        PFDDrawing schema (drawing_id, nodes, edges, etc.).

        If drawing_info (from DrawingInfoExpert) is provided, its non-empty
        fields populate the PFDDrawing metadata (drawing_id / drawing_name /
        drawing_number / revision / project / unit).
        """
        if not merged_topology:
            merged_topology = {}

        from src.core.models.unit.model_builder import build_pfd_drawing, pfd_drawing_to_dict

        drawing = build_pfd_drawing(
            page_index, merged_topology, page_label, drawing_info=drawing_info
        )
        return pfd_drawing_to_dict(drawing)

    @staticmethod
    def build_global_graph(page_graphs: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a global graph with page-aware node ids and cross-page edges.

        Called after all pages' equipment/boundary nodes are extracted.
        Generates cross-page edges by matching cross_drawing boundary nodes to
        equipment nodes on other pages via equipment_tag.

        Args:
            page_graphs: List of page graph dicts, each containing:
                - page_index: int
                - pfd_drawing: {nodes: [...], edges: [...]}

        Returns:
            Global graph dict with nodes (page-aware ids), edges (in-page +
            cross-page), cross_page_edges (CrossPageLink metadata), node_index.
        """
        from src.agent.utils.cross_page_stitcher import build_global_graph as _build

        return _build(page_graphs)
