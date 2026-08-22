"""装置级 BoundaryNodeExpert 提取专家评估算法。

输入：
  - label   : data/label/{id}.json 中 `boundary_nodes` 字段
  - extract : output/boundary_nodes/boundary_node.json 中 `boundary_node` 字段

评估维度：
  1. 边界节点识别 (Precision / Recall / F1)
     - 按 bbox 中心点最近距离贪心一一匹配
       （label 与 extraction 的 description/boundary_type 用词体系可能不同，
        位置是最稳定的对齐线索）
     - 设置距离阈值 `match_max_distance`，超出阈值不视为匹配
  2. bbox 准确率
     - 仅对匹配上的节点：平均 IoU、IoU≥阈值 命中率（默认 0.5）
  3. boundary_type 准确率（完全匹配率）
  4. equipment_tag 准确率（list 完全相同率，去除首尾空格、统一大小写后再比对）
  5. drawing_id 准确率（完全匹配率）

设计原则：
  - 用位置稳定对齐，再逐字段比对
  - 所有指标可定位到具体节点
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Union

from .metrics import MetricSet
from .equipment_evaluator import _bbox_iou, _bbox_center, _euclid


# ---------------------------------------------------------------------------
# Per-node diff
# ---------------------------------------------------------------------------


@dataclass
class BoundaryDiff:
    """单个匹配 boundary 节点的字段对比明细。"""

    label_id: str
    extraction_id: str
    description_label: str
    description_extraction: str
    center_distance: float
    bbox_iou: float
    bbox_hit_threshold: bool

    boundary_type_label: str
    boundary_type_extraction: str
    boundary_type_match: bool

    equipment_tag_label: list[str]
    equipment_tag_extraction: list[str]
    equipment_tag_match: bool

    drawing_id_label: str
    drawing_id_extraction: str
    drawing_id_match: bool


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class BoundaryEvaluationReport:
    sample_id: str = ""
    bbox_iou_threshold: float = 0.5
    match_max_distance: float = 0.1  # 中心点距离阈值（归一化坐标）

    boundary_metric: MetricSet = field(default_factory=MetricSet)
    label_unmatched: list[str] = field(default_factory=list)  # description / id
    extraction_unmatched: list[str] = field(default_factory=list)

    diffs: list[BoundaryDiff] = field(default_factory=list)

    bbox_mean_iou: float = 0.0
    bbox_hit_rate: float = 0.0
    boundary_type_accuracy: float = 0.0
    equipment_tag_accuracy: float = 0.0
    drawing_id_accuracy: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "bbox_iou_threshold": self.bbox_iou_threshold,
            "match_max_distance": self.match_max_distance,
            "boundary_detection": self.boundary_metric.as_dict(),
            "bbox": {
                "mean_iou": round(self.bbox_mean_iou, 4),
                "hit_rate": round(self.bbox_hit_rate, 4),
                "iou_threshold": self.bbox_iou_threshold,
            },
            "boundary_type_accuracy": round(self.boundary_type_accuracy, 4),
            "equipment_tag_accuracy": round(self.equipment_tag_accuracy, 4),
            "drawing_id_accuracy": round(self.drawing_id_accuracy, 4),
            "label_unmatched": self.label_unmatched,
            "extraction_unmatched": self.extraction_unmatched,
            "details": [
                {
                    "label_id": d.label_id,
                    "extraction_id": d.extraction_id,
                    "description": {
                        "label": d.description_label,
                        "extraction": d.description_extraction,
                    },
                    "center_distance": round(d.center_distance, 4),
                    "bbox_iou": round(d.bbox_iou, 4),
                    "bbox_hit": d.bbox_hit_threshold,
                    "boundary_type": {
                        "label": d.boundary_type_label,
                        "extraction": d.boundary_type_extraction,
                        "match": d.boundary_type_match,
                    },
                    "equipment_tag": {
                        "label": d.equipment_tag_label,
                        "extraction": d.equipment_tag_extraction,
                        "match": d.equipment_tag_match,
                    },
                    "drawing_id": {
                        "label": d.drawing_id_label,
                        "extraction": d.drawing_id_extraction,
                        "match": d.drawing_id_match,
                    },
                }
                for d in self.diffs
            ],
        }

    def print_summary(self) -> None:
        print(f"\n{'=' * 70}")
        print(f"Boundary Extraction Evaluation - Sample: {self.sample_id}")
        print(f"{'=' * 70}")

        m = self.boundary_metric
        print("\n[1] Boundary Detection (bbox center nearest, "
              f"max dist={self.match_max_distance})")
        print(f"    TP={m.tp}  FP={m.fp}  FN={m.fn}")
        print(f"    Precision: {m.precision:.4f}  Recall: {m.recall:.4f}  F1: {m.f1:.4f}")

        print("\n[2] BBox Accuracy (on matched boundaries)")
        print(f"    Mean IoU: {self.bbox_mean_iou:.4f}")
        print(f"    Hit rate (IoU >= {self.bbox_iou_threshold}): "
              f"{self.bbox_hit_rate:.4f}")

        print("\n[3] boundary_type Accuracy")
        print(f"    Accuracy: {self.boundary_type_accuracy:.4f}")

        print("\n[4] equipment_tag Accuracy (list exact match)")
        print(f"    Accuracy: {self.equipment_tag_accuracy:.4f}")

        print("\n[5] drawing_id Accuracy")
        print(f"    Accuracy: {self.drawing_id_accuracy:.4f}")

        if self.label_unmatched:
            print("\n[Unmatched label boundaries (FN)]")
            for s in self.label_unmatched:
                print(f"  - {s}")
        if self.extraction_unmatched:
            print("\n[Unmatched extraction boundaries (FP)]")
            for s in self.extraction_unmatched:
                print(f"  - {s}")
        print(f"\n{'=' * 70}")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_label_boundary(label_path: Union[str, Path]) -> list[dict[str, Any]]:
    with open(label_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("boundary_nodes", []) or [])


def _load_extraction_boundary(extraction_path: Union[str, Path]) -> list[dict[str, Any]]:
    with open(extraction_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        # 兼容 boundary_node.json (top-level "boundary_node") /
        #      boundary_node_result.json (top-level "data.boundary_node")
        for key in ("boundary_node", "boundary_nodes"):
            if key in data and isinstance(data[key], list):
                return list(data[key])
        if "data" in data and isinstance(data["data"], dict):
            for key in ("boundary_node", "boundary_nodes"):
                inner = data["data"].get(key)
                if isinstance(inner, list):
                    return list(inner)
    raise ValueError(
        f"Unsupported extraction format: {extraction_path}. "
        f"Expected top-level 'boundary_node' list or 'data.boundary_node'."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_tag_for_compare(tag: str) -> str:
    return (tag or "").strip().upper().replace(" ", "")


def _normalize_tag_list(tags: Any) -> list[str]:
    """归一化 equipment_tag list 用于比较：去除空白、空字符串与重复，排序。"""
    if not isinstance(tags, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for t in tags:
        if not isinstance(t, str):
            continue
        norm = _normalize_tag_for_compare(t)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    out.sort()
    return out


# ---------------------------------------------------------------------------
# Core evaluator
# ---------------------------------------------------------------------------


class BoundaryEvaluator:
    """装置级边界节点提取评估器。

    Usage:
        evaluator = BoundaryEvaluator()
        report = evaluator.evaluate(
            label_path="data/label/001.json",
            extraction_path="output/boundary_nodes/boundary_node.json",
            sample_id="001",
        )
        report.print_summary()
    """

    def __init__(
        self,
        bbox_iou_threshold: float = 0.5,
        match_max_distance: float = 0.1,
    ) -> None:
        self.bbox_iou_threshold = bbox_iou_threshold
        self.match_max_distance = match_max_distance

    # --- public API ---

    def evaluate(
        self,
        label_path: Union[str, Path],
        extraction_path: Union[str, Path],
        sample_id: str = "",
    ) -> BoundaryEvaluationReport:
        label_bs = _load_label_boundary(label_path)
        ext_bs = _load_extraction_boundary(extraction_path)
        return self.evaluate_from_lists(label_bs, ext_bs, sample_id=sample_id)

    def evaluate_from_lists(
        self,
        label_boundaries: list[dict[str, Any]],
        extraction_boundaries: list[dict[str, Any]],
        sample_id: str = "",
    ) -> BoundaryEvaluationReport:
        report = BoundaryEvaluationReport(
            sample_id=sample_id,
            bbox_iou_threshold=self.bbox_iou_threshold,
            match_max_distance=self.match_max_distance,
        )

        # 1) 节点匹配：bbox 中心点最近贪心
        matched_pairs, unmatched_label, unmatched_ext = self._match_boundaries(
            label_boundaries, extraction_boundaries
        )
        report.boundary_metric = MetricSet(
            tp=len(matched_pairs),
            fp=len(unmatched_ext),
            fn=len(unmatched_label),
        )
        report.label_unmatched = [
            (b.get("description") or b.get("id") or "") for b in unmatched_label
        ]
        report.extraction_unmatched = [
            (b.get("description") or b.get("id") or "") for b in unmatched_ext
        ]

        # 2-5) 仅对匹配节点做字段比对
        iou_list: list[float] = []
        hits = 0
        type_correct = 0
        eq_tag_correct = 0
        drawing_correct = 0

        for label_b, ext_b, dist in matched_pairs:
            diff = self._diff_boundary(label_b, ext_b, dist)
            report.diffs.append(diff)

            iou_list.append(diff.bbox_iou)
            if diff.bbox_hit_threshold:
                hits += 1
            if diff.boundary_type_match:
                type_correct += 1
            if diff.equipment_tag_match:
                eq_tag_correct += 1
            if diff.drawing_id_match:
                drawing_correct += 1

        n = len(matched_pairs)
        report.bbox_mean_iou = sum(iou_list) / n if n else 0.0
        report.bbox_hit_rate = hits / n if n else 0.0
        report.boundary_type_accuracy = type_correct / n if n else 0.0
        report.equipment_tag_accuracy = eq_tag_correct / n if n else 0.0
        report.drawing_id_accuracy = drawing_correct / n if n else 0.0

        return report

    # --- internal helpers ---

    def _match_boundaries(
        self,
        label_bs: list[dict[str, Any]],
        ext_bs: list[dict[str, Any]],
    ) -> tuple[
        list[tuple[dict[str, Any], dict[str, Any], float]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """按 bbox 中心点最近距离贪心一一匹配。

        距离超过 `match_max_distance` 的对不视为匹配。
        """
        # 计算所有 pair 距离
        pairs: list[tuple[float, int, int]] = []
        for li, lb in enumerate(label_bs):
            lcenter = _bbox_center(lb.get("bbox") or [])
            if lcenter is None:
                continue
            for ei, eb in enumerate(ext_bs):
                ecenter = _bbox_center(eb.get("bbox") or [])
                if ecenter is None:
                    continue
                dist = _euclid(lcenter, ecenter)
                if dist > self.match_max_distance:
                    continue
                pairs.append((dist, li, ei))
        pairs.sort(key=lambda x: x[0])

        used_label: set[int] = set()
        used_ext: set[int] = set()
        matched: list[tuple[dict[str, Any], dict[str, Any], float]] = []
        for dist, li, ei in pairs:
            if li in used_label or ei in used_ext:
                continue
            matched.append((label_bs[li], ext_bs[ei], dist))
            used_label.add(li)
            used_ext.add(ei)

        unmatched_label = [label_bs[i] for i in range(len(label_bs)) if i not in used_label]
        unmatched_ext = [ext_bs[j] for j in range(len(ext_bs)) if j not in used_ext]
        return matched, unmatched_label, unmatched_ext

    def _diff_boundary(
        self,
        label_b: dict[str, Any],
        ext_b: dict[str, Any],
        center_distance: float,
    ) -> BoundaryDiff:
        iou = _bbox_iou(label_b.get("bbox") or [], ext_b.get("bbox") or [])

        bt_l = (label_b.get("boundary_type") or "").strip()
        bt_e = (ext_b.get("boundary_type") or "").strip()

        eq_l = _normalize_tag_list(label_b.get("equipment_tag"))
        eq_e = _normalize_tag_list(ext_b.get("equipment_tag"))

        dr_l = (label_b.get("drawing_id") or "").strip()
        dr_e = (ext_b.get("drawing_id") or "").strip()

        return BoundaryDiff(
            label_id=label_b.get("id", ""),
            extraction_id=ext_b.get("id", ""),
            description_label=(label_b.get("description") or ""),
            description_extraction=(ext_b.get("description") or ""),
            center_distance=center_distance,
            bbox_iou=iou,
            bbox_hit_threshold=iou >= self.bbox_iou_threshold,
            boundary_type_label=bt_l,
            boundary_type_extraction=bt_e,
            boundary_type_match=(bt_l == bt_e and bt_l != ""),
            equipment_tag_label=eq_l,
            equipment_tag_extraction=eq_e,
            equipment_tag_match=(eq_l == eq_e),
            drawing_id_label=dr_l,
            drawing_id_extraction=dr_e,
            drawing_id_match=(dr_l == dr_e),
        )


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def evaluate_boundary_sample(
    sample_id: str,
    label_dir: Union[str, Path] = "data/label",
    extraction_path: Union[str, Path, None] = None,
    bbox_iou_threshold: float = 0.5,
    match_max_distance: float = 0.1,
) -> BoundaryEvaluationReport:
    """按 sample_id 评估一个样本。

    默认路径:
      label:      {label_dir}/{sample_id}.json
      extraction: output/boundary_nodes/boundary_node.json
    """
    label_path = Path(label_dir) / f"{sample_id}.json"
    if extraction_path is None:
        extraction_path = Path("output/boundary_nodes/boundary_node.json")
    if not label_path.exists():
        raise FileNotFoundError(f"Label file not found: {label_path}")
    if not Path(extraction_path).exists():
        raise FileNotFoundError(f"Extraction file not found: {extraction_path}")
    evaluator = BoundaryEvaluator(
        bbox_iou_threshold=bbox_iou_threshold,
        match_max_distance=match_max_distance,
    )
    return evaluator.evaluate(label_path, extraction_path, sample_id=sample_id)
