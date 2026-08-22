"""Plant-Unit Topology Workflow（合并版）.

全厂装置拓扑提取统一工作流：先由 VLM 分类专家判别图纸类型，再走对应提取路径。

编排：
- Phase 0: ``PlantUnitDrawingTypeExpert`` 判别图纸类型
  - plant_unit_general（有管线连接）→ Phase 1 用 plant_unit_general prompt
  - plant_unit_dense（物料表无管线）→ Phase 1 用 plant_unit_dense prompt
  - unknown → 抛 ``PFDAnalysisError``，要求用户重新上传符合要求的图纸
- Phase 1: ``PlantUnitExpert`` 按判别类型提取装置节点（带 feeds + products）
- Phase 2: 按类型走对应拓扑提取路径
  - general: ``PlantUnitTopologyExpertOneByOne`` 逐单元 VLM + 校验 + 回补（默认，
    general_topology_mode="one_by_one"）；或 ``PlantUnitTopologyExpert`` 整图单次
    VLM（general_topology_mode="all_in_one"），后续同样走校验 + 回补
  - dense: ``infer_topology_by_material_matching`` 物料名匹配算法（无 VLM）
- Phase 3: 合并节点 + 拓扑为 PlantUnitDrawing
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

from src.agent.experts.plant.plant_unit_drawing_type import PlantUnitDrawingTypeExpert
from src.agent.experts.plant.plant_unit_node import PlantUnitExpert
from src.agent.experts.plant.plant_unit_topology import (
    PlantUnitTopologyExpert,
    PlantUnitTopologyExpertOneByOne,
    build_plant_unit_drawing,
)
from src.agent.workflow.core import BaseWorkflow
from src.agent.workflow.plant.topology_validation import (
    fallback_material_matching,
    infer_topology_by_material_matching,
    validate_edges_against_feeds,
)
from duck.content import Content
from duck.host_client import HostClient
from src.core import Settings, get_logger
from src.core.infra.exceptions import CancelledByClientError, PFDAnalysisError

logger = get_logger(__name__)


class PlantUnitTopologyWorkflow(BaseWorkflow):
    """全厂装置拓扑提取工作流：先判类型，再走对应路径提取节点与拓扑。

    替代原 PlantUnitTopologyGeneralWorkflow 和 PlantUnitTopologyDenseWorkflow。
    分类为 unknown 时抛 PFDAnalysisError，要求用户重新上传符合要求的图纸。
    """

    workflow_name = "plant_unit_topology"

    def __init__(
        self,
        settings: Settings,
        max_workers: int = 1,
        prompt_version: Optional[str] = None,
        general_topology_mode: str = "one_by_one",
        content: Optional[Content] = None,
        host_client: Optional[HostClient] = None,
    ) -> None:
        if general_topology_mode not in ("one_by_one", "all_in_one"):
            raise ValueError(
                f"Invalid general_topology_mode: {general_topology_mode!r}, "
                f"expected 'one_by_one' or 'all_in_one'"
            )
        self._prompt_version = prompt_version
        self._general_topology_mode = general_topology_mode
        super().__init__(
            settings=settings,
            max_workers=max_workers,
            content=content,
            host_client=host_client,
        )

    def _init_experts(self) -> None:
        self.drawing_type_expert = PlantUnitDrawingTypeExpert(settings=self.settings)
        if self._general_topology_mode == "all_in_one":
            self.topology_expert: PlantUnitTopologyExpert = PlantUnitTopologyExpert(
                settings=self.settings,
                prompt_version=self._prompt_version,
            )
        else:
            self.topology_expert = PlantUnitTopologyExpertOneByOne(
                settings=self.settings,
                prompt_version=self._prompt_version,
            )
        # unit_expert 延迟到 Phase 1 创建：plant_unit_type 由 Phase 0 分类结果决定

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        image_path: str,
        cancel_event: Optional[threading.Event] = None,
    ) -> dict[str, Any]:
        """Run the four-phase extraction and return a merged result dict."""
        self._cancel_event = cancel_event
        self._content.send_progress_with_data(0, total=4, message="Starting plant-unit topology extraction")

        # 通过 HostClient 加载图片为内存 Image（不触碰本地文件 API）
        loaded_image = self._load_image(image_path) if self._host_client else None
        image = Path(image_path)
        if loaded_image is None and not image.exists():
            raise PFDAnalysisError(f"Image file not found: {image}")

        self.logger.info("=" * 80)
        self.logger.info(f"Workflow: {self.workflow_name} started")
        self.logger.info(f"Input: {image_path}")
        self.logger.info("=" * 80)

        # Phase 0: 图纸类型判别
        self._content.send_progress_with_data(0.5, total=4, message="Classifying drawing type")
        drawing_type, type_result = self._classify_drawing_type(str(image), loaded_image)
        self.logger.info(
            f"Phase 0 done: drawing_type={drawing_type} "
            f"confidence={type_result.get('confidence', 0.0)}"
        )
        self._content.send_progress_with_data(
            1,
            total=4,
            message=f"Drawing type classified: {drawing_type}",
            ui_event={
                "event_type": "drawing_type_classified",
                "drawing_type": drawing_type,
                "confidence": type_result.get("confidence", 0.0),
            },
        )
        if self._cancel_event and self._cancel_event.is_set():
            raise CancelledByClientError("客户端取消（图纸类型判别后）")

        # Phase 1: 装置节点提取（按判别类型构造专家）
        self._content.send_progress_with_data(1.5, total=4, message="Extracting plant unit nodes")
        unit_expert = PlantUnitExpert(
            settings=self.settings,
            prompt_version=self._prompt_version,
            plant_unit_type=drawing_type,
        )
        unit_output = unit_expert.analyze(str(image), loaded_image=loaded_image, cancel_event=self._cancel_event)
        if not unit_output.success:
            raise PFDAnalysisError(
                f"Plant unit node extraction failed: {unit_output.errors}"
            )
        unit_result = unit_output.data
        plant_units = unit_result.get("plant_unit", [])
        self.logger.info(
            f"Phase 1 done: {len(plant_units)} plant units extracted "
            f"({len(unit_result.get('text_destinations', []))} text destinations)"
        )
        self._content.send_progress_with_data(
            2,
            total=4,
            message=f"{len(plant_units)} plant units extracted",
            ui_event={
                "event_type": "plant_units_extracted",
                "unit_count": len(plant_units),
                "text_destination_count": len(unit_result.get("text_destinations", [])),
                "partial_plant_units": plant_units,
                "partial_text_destinations": unit_result.get("text_destinations", []),
            },
        )
        if self._cancel_event and self._cancel_event.is_set():
            raise CancelledByClientError("客户端取消（装置节点提取后）")

        # Phase 2: 拓扑提取（按 drawing_type 分支）
        self._content.send_progress_with_data(2.5, total=4, message="Extracting topology")
        if drawing_type == "plant_unit_general":
            topology_result = self._extract_topology_general(str(image), unit_result, loaded_image)
        else:
            topology_result = self._extract_topology_dense(unit_result)

        self._content.send_progress_with_data(
            3,
            total=4,
            message="Topology extracted",
            ui_event={
                "event_type": "topology_extracted",
                "edges_count": len(topology_result.get("edges", [])),
                "topology_source": topology_result.get("topology_source", "vlm"),
                "partial_edges": topology_result.get("edges", []),
            },
        )
        if self._cancel_event and self._cancel_event.is_set():
            raise CancelledByClientError("客户端取消（拓扑提取后）")

        # Phase 3: 合并节点 + 拓扑为 PlantUnitDrawing
        drawing = build_plant_unit_drawing(unit_result, topology_result)
        drawing_dict = drawing.to_dict()

        result: dict[str, Any] = {
            "version": "1.0.0",
            "workflow": self.workflow_name,
            "drawing_type": drawing_type,
            "status": "success",
            "plant_unit_drawing": drawing_dict,
            "expert_outputs": {
                "plant_unit_drawing_type": type_result,
                "plant_unit": unit_result,
                "plant_unit_topology": topology_result,
            },
            "drawing_type_detection": {
                "drawing_type": drawing_type,
                "evidence": type_result.get("evidence", ""),
                "confidence": type_result.get("confidence", 0.0),
            },
            "warnings": list(type_result.get("warnings", []))
            + list(unit_result.get("warnings", []))
            + list(topology_result.get("warnings", [])),
            "errors": [],
        }

        self._content.send_progress_with_data(4, total=4, message="Plant-unit topology extraction completed")
        self.logger.info("=" * 80)
        self.logger.info("Plant-unit topology workflow completed")
        self.logger.info("=" * 80)
        return result

    # ------------------------------------------------------------------
    # Phase 0: 图纸类型判别
    # ------------------------------------------------------------------

    def _classify_drawing_type(
        self, image_path: str, loaded_image=None
    ) -> tuple[str, dict[str, Any]]:
        """调 PlantUnitDrawingTypeExpert 判别图纸类型，unknown 时抛错。"""
        self.logger.info("Phase 0: classifying plant-unit drawing type")
        type_output = self.drawing_type_expert.analyze(
            image_path, loaded_image=loaded_image, cancel_event=self._cancel_event
        )
        if not type_output.success:
            raise PFDAnalysisError(
                f"Drawing type classification failed: {type_output.errors}"
            )
        type_result = type_output.data
        drawing_type = type_result.get("drawing_type", "unknown")
        if drawing_type == "unknown":
            raise PFDAnalysisError(
                "无法判定图纸类型(drawing_type=unknown)，"
                "请重新上传含管线连接(plant_unit_general)或物料信息表(plant_unit_dense)的整厂流程图"
            )
        return drawing_type, type_result

    # ------------------------------------------------------------------
    # Phase 2a: general 路径——VLM 拓扑提取
    # ------------------------------------------------------------------

    def _extract_topology_general(
        self, image_path: str, unit_result: dict[str, Any], loaded_image=None
    ) -> dict[str, Any]:
        """general 路径：VLM 提取（one_by_one 逐单元 / all_in_one 整图）+ 校验 + 回补。"""
        plant_units: list[dict[str, Any]] = unit_result.get("plant_unit", []) or []
        total = len(plant_units)
        if total == 0:
            self.logger.warning(
                "No plant units extracted; skip topology extraction"
            )
            return {
                "drawing_id": unit_result.get("drawing_id", "plant_unit_drawing_1"),
                "drawing_name": unit_result.get("drawing_name", ""),
                "edges": [],
                "topology_source": "vlm",
                "warnings": [],
            }

        context_base: dict[str, Any] = {
            "plant_unit": plant_units,
            "text_destinations": unit_result.get("text_destinations", []),
            "drawing_id": unit_result.get("drawing_id", "plant_unit_drawing_1"),
            "drawing_name": unit_result.get("drawing_name", ""),
        }

        self.logger.info(
            f"Phase 2 (general): running {self._general_topology_mode} topology "
            f"for {total} units (max_workers={self.max_workers})"
        )

        warnings: list[str] = []
        if self._general_topology_mode == "all_in_one":
            # 整图单次 VLM 调用提取全部拓扑边
            expert_output = self.topology_expert.analyze(
                image_path, context=context_base, loaded_image=loaded_image,
                cancel_event=self._cancel_event
            )
            if expert_output.success and expert_output.data:
                merged_edges = expert_output.data.get("edges", []) or []
                warnings.extend(expert_output.data.get("warnings", []) or [])
            else:
                self.logger.warning(
                    f"all_in_one topology extraction failed: {expert_output.errors}"
                )
                merged_edges = []
                warnings.extend(expert_output.errors or [])
        else:
            per_unit_outputs: list[Optional[dict[str, Any]]] = [None] * total

            def _run(idx_unit: tuple[int, dict[str, Any]]) -> tuple[int, dict[str, Any]]:
                idx, unit = idx_unit
                return idx, self._run_single_unit(
                    image_path, unit, idx + 1, total, context_base, loaded_image
                )

            tasks = list(enumerate(plant_units))
            if self.max_workers <= 1 or total == 1:
                for idx, unit in tasks:
                    slot, data = _run((idx, unit))
                    per_unit_outputs[slot] = data
            else:
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    future_to_idx = {executor.submit(_run, t): t[0] for t in tasks}
                    for future in as_completed(future_to_idx):
                        slot = future_to_idx[future]
                        _, data = future.result()
                        per_unit_outputs[slot] = data

            outputs: list[dict[str, Any]] = [o for o in per_unit_outputs if o is not None]
            merged_edges = PlantUnitTopologyExpertOneByOne._merge_edges(outputs)
            for output in outputs:
                warnings.extend(output.get("warnings", []) or [])
                warnings.extend(output.get("errors", []) or [])

        self.logger.info(
            f"Phase 2 (general) done: {len(merged_edges)} edges extracted"
        )

        # Phase 2b: 后校验——移除 VLM 幻觉边（target feeds 不含该物料）
        text_destinations = unit_result.get("text_destinations", []) or []
        before_val = len(merged_edges)
        merged_edges, val_warnings = validate_edges_against_feeds(
            merged_edges, plant_units, text_destinations
        )
        if val_warnings:
            self.logger.info(
                f"Phase 2b (validation): removed {before_val - len(merged_edges)} "
                f"invalid edges"
            )
            warnings.extend(val_warnings)

        # Phase 2c: 回补——为 VLM 未提取到出边的装置用物料名匹配补边
        before_fb = len(merged_edges)
        merged_edges, fb_warnings = fallback_material_matching(
            merged_edges, plant_units, text_destinations
        )
        if fb_warnings:
            self.logger.info(
                f"Phase 2c (fallback): added {len(merged_edges) - before_fb} "
                f"fallback edges"
            )
            warnings.extend(fb_warnings)

        return {
            "drawing_id": unit_result.get("drawing_id", "plant_unit_drawing_1"),
            "drawing_name": unit_result.get("drawing_name", ""),
            "edges": merged_edges,
            "topology_source": "vlm",
            "warnings": warnings,
        }

    def _run_single_unit(
        self,
        image_path: str,
        unit: dict[str, Any],
        index: int,
        total: int,
        context_base: dict[str, Any],
        loaded_image=None,
    ) -> dict[str, Any]:
        unit_id = str(unit.get("id") or f"unit_{index:03d}")
        unit_name = unit.get("unit_name") or unit.get("name") or unit_id
        self.logger.info(
            f"  [{index}/{total}] one-by-one topology for '{unit_name}' ({unit_id})"
        )

        unit_context = {
            **context_base,
            "current_unit": unit,
            "unit_index": index,
            "unit_count": total,
        }
        expert_output = self.topology_expert.analyze(
            image_path, context=unit_context, loaded_image=loaded_image,
            cancel_event=self._cancel_event
        )

        if expert_output.success and expert_output.data:
            data = expert_output.data
            return {
                "current_unit_id": unit_id,
                "edges": data.get("edges", []),
                "warnings": list(data.get("warnings", []) or []),
            }

        self.logger.warning(
            f"  [{index}/{total}] failed for '{unit_id}': {expert_output.errors}"
        )
        return {
            "current_unit_id": unit_id,
            "edges": [],
            "warnings": [],
            "errors": list(expert_output.errors or []),
        }

    # ------------------------------------------------------------------
    # Phase 2b: dense 路径——物料名匹配算法（无 VLM）
    # ------------------------------------------------------------------

    def _extract_topology_dense(
        self, unit_result: dict[str, Any]
    ) -> dict[str, Any]:
        """dense 路径：物料名匹配算法推理拓扑（无 VLM）。"""
        plant_units: list[dict[str, Any]] = unit_result.get("plant_unit", []) or []
        if not plant_units:
            self.logger.warning(
                "No plant units extracted; skip material-matching topology inference"
            )
            return {
                "drawing_id": unit_result.get("drawing_id", "plant_unit_drawing_1"),
                "drawing_name": unit_result.get("drawing_name", ""),
                "edges": [],
                "topology_source": "material_matching",
                "warnings": [],
            }

        self.logger.info(
            f"Phase 2 (dense): inferring topology by material matching for "
            f"{len(plant_units)} units"
        )

        edges = infer_topology_by_material_matching(plant_units)

        self.logger.info(
            f"Phase 2 (dense) done: {len(edges)} edges extracted"
        )

        return {
            "drawing_id": unit_result.get("drawing_id", "plant_unit_drawing_1"),
            "drawing_name": unit_result.get("drawing_name", ""),
            "edges": edges,
            "topology_source": "material_matching",
            "warnings": [],
            "match_summary": {
                "matched_units": len({e["source_node_id"] for e in edges}),
                "total_edges": len(edges),
            },
        }

    def _log_workflow_info(self) -> None:
        logger.info("=" * 60)
        logger.info(f"Workflow: {self.workflow_name}")
        logger.info(f"max_workers: {self.max_workers}")
        logger.info(
            f"  DrawingType Expert prompt: {self.drawing_type_expert._prompt_builder.version}"
        )
        logger.info(
            f"  Topology ({self._general_topology_mode}) prompt: "
            f"{self.topology_expert._prompt_builder.version}"
        )
        logger.info(
            f"  Topology mode (general): {self._general_topology_mode}"
        )
        logger.info("  Topology source: auto (general=vlm / dense=material_matching)")
        logger.info("=" * 60)
