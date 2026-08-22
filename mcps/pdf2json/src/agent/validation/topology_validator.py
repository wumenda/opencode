"""拓扑后校验：聚合 graph_checks + equipment_ports 既有实现，产出 TopologyValidationResult。

仅做检测与报告，不做自动修复（自动修复是独立 P1 项）。
入参为 PFDDrawing 模型对象（graph_checks 用 getattr 取属性，须为 StreamEdge 模型）。
"""
from __future__ import annotations

from typing import Any

from src.core.infra.settings_validation import ValidationSettings
from src.core.models.unit.drawing import PFDDrawing
from src.core.models.unit.enums import BoundaryType
from src.core.models.unit.nodes import BoundaryNode, PFDEquipmentNode
from src.core.models.unit.equipment_ports import (
    check_equipment_channel,
    check_equipment_port_count,
)
from src.core.models.core.graph_checks import (
    find_dangling_edge_refs,
    find_duplicate_edges,
    find_duplicate_stream_numbers,
    find_orphan_node_ids,
    find_self_loop_edges,
    find_unreachable_from_boundary,
)
from src.core.models.core.validation_results import (
    TopologyValidationResult,
    ValidationIssue,
)


class TopologyValidator:
    """对 PFDDrawing 运行图结构 + 端口约束校验，聚合为 TopologyValidationResult。"""

    def __init__(self, settings: ValidationSettings) -> None:
        self.settings = settings

    def validate(self, drawing: PFDDrawing) -> TopologyValidationResult:
        issues: list[ValidationIssue] = []
        needs_human_review: list[str] = []

        nodes = list(drawing.nodes)
        edges = list(drawing.edges)
        node_ids = [n.id for n in nodes]
        valid_node_ids = set(node_ids)

        if self.settings.enable_rule_validator:
            self._check_self_loops(edges, issues)
            self._check_dangling_refs(edges, valid_node_ids, issues, needs_human_review)
            self._check_orphans(node_ids, edges, issues, needs_human_review)
            self._check_duplicate_edges(edges, issues)
            self._check_unreachable(node_ids, edges, nodes, issues, needs_human_review)
            self._check_duplicate_stream_numbers(edges, issues)

        if self.settings.check_port_constraints:
            self._check_port_constraints(nodes, issues, needs_human_review)

        status = self._derive_status(issues)
        return TopologyValidationResult(
            validation_status=status,
            issues=issues,
            auto_fixed=[],
            needs_human_review=needs_human_review,
        )

    # ── graph_checks 子检查 ──

    @staticmethod
    def _check_self_loops(edges: list[Any], issues: list[ValidationIssue]) -> None:
        for item in find_self_loop_edges(edges):
            issues.append(ValidationIssue(
                severity="warning",
                type="self_loop_edge",
                edge_id=item["edge_id"],
                node_id=item["node_id"],
                description=f"边 {item['edge_id']} 为自环（节点 {item['node_id']} 自身端口 {item['source_port']} 连自身）",
                suggestion="检查是否为模型误识别；自环边通常无物理意义",
            ))

    @staticmethod
    def _check_dangling_refs(
        edges: list[Any],
        valid_node_ids: set[str],
        issues: list[ValidationIssue],
        needs_human_review: list[str],
    ) -> None:
        for item in find_dangling_edge_refs(edges, valid_node_ids):
            issues.append(ValidationIssue(
                severity="error",
                type="dangling_edge_ref",
                edge_id=item["edge_id"],
                description=(
                    f"边 {item['edge_id']} 的 {item['missing_type']} 节点 "
                    f"'{item['missing_node_id']}' 不存在（悬空引用）"
                ),
                suggestion="检查拓扑专家是否编造了不存在的节点 id，或上游节点被误删",
            ))
            needs_human_review.append(item["edge_id"])

    @staticmethod
    def _check_orphans(
        node_ids: list[str],
        edges: list[Any],
        issues: list[ValidationIssue],
        needs_human_review: list[str],
    ) -> None:
        for nid in find_orphan_node_ids(node_ids, edges):
            issues.append(ValidationIssue(
                severity="warning",
                type="orphan_node",
                node_id=nid,
                description=f"节点 '{nid}' 未出现在任何边中（孤立节点）",
                suggestion="检查是否漏识别了连接边，或节点为误识别",
            ))
            needs_human_review.append(nid)

    @staticmethod
    def _check_duplicate_edges(edges: list[Any], issues: list[ValidationIssue]) -> None:
        for item in find_duplicate_edges(edges):
            issues.append(ValidationIssue(
                severity="warning",
                type="duplicate_edge",
                edge_id=item["edge_id"],
                description=(
                    f"边 {item['edge_id']} 与 {item['all_edge_ids']} "
                    f"为重复边（{item['source']}→{item['target']}，端口相同）"
                ),
                suggestion="检查是否为模型重复输出同一条流股",
            ))

    @staticmethod
    def _check_unreachable(
        node_ids: list[str],
        edges: list[Any],
        nodes: list[Any],
        issues: list[ValidationIssue],
        needs_human_review: list[str],
    ) -> None:
        boundary_in_ids = [
            n.id for n in nodes
            if isinstance(n, BoundaryNode)
            and n.boundary_type in (BoundaryType.BOUNDARY_IN, BoundaryType.CROSS_DRAWING_IN)
        ]
        boundary_out_ids = [
            n.id for n in nodes
            if isinstance(n, BoundaryNode)
            and n.boundary_type in (BoundaryType.BOUNDARY_OUT, BoundaryType.CROSS_DRAWING_OUT)
        ]
        for item in find_unreachable_from_boundary(
            node_ids, edges, boundary_in_ids, boundary_out_ids
        ):
            issues.append(ValidationIssue(
                severity="warning",
                type="unreachable_from_boundary",
                node_id=item["node_id"],
                description=(
                    f"节点 '{item['node_id']}' 从界区进料边界不可达"
                    f"（类型: {item['type']}），可能存在断链"
                ),
                suggestion="检查相邻边是否漏识别，或边界方向是否标反",
            ))
            needs_human_review.append(item["node_id"])

    @staticmethod
    def _check_duplicate_stream_numbers(
        edges: list[Any], issues: list[ValidationIssue]
    ) -> None:
        for item in find_duplicate_stream_numbers(edges):
            issues.append(ValidationIssue(
                severity="info",
                type="duplicate_stream_number",
                edge_id=item["edge_id"],
                description=(
                    f"流股号 '{item['stream_number']}' 被多条边共用: "
                    f"{item['all_edge_ids']}"
                ),
                suggestion="同一流股号通常对应单条边，检查是否拆分错误",
            ))

    @staticmethod
    def _check_port_constraints(
        nodes: list[Any],
        issues: list[ValidationIssue],
        needs_human_review: list[str],
    ) -> None:
        for node in nodes:
            if not isinstance(node, PFDEquipmentNode):
                continue
            violation = check_equipment_port_count(node)
            if violation is None:
                continue
            issues.append(ValidationIssue(
                severity="warning",
                type="port_count_violation",
                node_id=violation.node_id,
                equipment_id=violation.node_id,
                description=(
                    f"设备 '{violation.node_id}'（{violation.equipment_type}）端口数违规: "
                    f"实际 {violation.in_count} 进 / {violation.out_count} 出，"
                    f"约束 {violation.constraint.min_in}-{violation.constraint.max_in} 进 / "
                    f"{violation.constraint.min_out}-{violation.constraint.max_out} 出；"
                    f"{'; '.join(violation.violations)}"
                ),
                suggestion="检查设备端口是否漏识别，或 equipment_type 是否误判",
            ))
            needs_human_review.append(violation.node_id)

        for node in nodes:
            if not isinstance(node, PFDEquipmentNode):
                continue
            ch_violation = check_equipment_channel(node)
            if ch_violation is None:
                continue
            issues.append(ValidationIssue(
                severity="warning",
                type="port_channel_violation",
                node_id=ch_violation.node_id,
                equipment_id=ch_violation.node_id,
                description=(
                    f"设备 '{ch_violation.node_id}'（{ch_violation.equipment_type}）"
                    f"端口 channel 配对违规：{'; '.join(ch_violation.violations)}"
                ),
                suggestion="检查端口 channel 标注是否正确：同 channel 端口在设备内部连通，需含 input/output 配对",
            ))
            if ch_violation.node_id not in needs_human_review:
                needs_human_review.append(ch_violation.node_id)

    @staticmethod
    def _derive_status(issues: list[ValidationIssue]) -> str:
        if any(i.severity == "error" for i in issues):
            return "needs_review"
        if any(i.severity == "warning" for i in issues):
            return "passed_with_warnings"
        return "passed"


def run_post_validation(
    state: Any,
    merged_topology: dict[str, Any],
    validation_settings: ValidationSettings,
) -> None:
    """对 merged_topology 运行后校验，结果写入 state.validation.validation_result。

    构建 PFDDrawing 模型（graph_checks 需 StreamEdge 模型对象，非 dict），
    交由 TopologyValidator 校验，写入 state.validation.validation_result。
    异常不中断主流程，仅记录到 state.warnings（校验是辅助环节）。
    """
    from src.core.models.unit.model_builder import build_pfd_drawing

    try:
        drawing = build_pfd_drawing(0, merged_topology or {})
        validator = TopologyValidator(validation_settings)
        state.validation.validation_result = validator.validate(drawing)
    except Exception as e:  # noqa: BLE001 — 校验失败不应中断提取主流程
        state.warnings.append(f"validation: post-validation skipped due to error: {e}")
