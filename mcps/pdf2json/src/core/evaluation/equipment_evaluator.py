"""装置级设备节点提取专家(EquipmentExpert)评估算法。

输入：
  - label   : data/label/{id}.json 中 `equipment_nodes` 字段（手工标注的标准答案）
  - extract : output/equipment_nodes/equipment.json 中 `equipment` 字段（专家输出）

评估维度：
  1. 设备识别 (Precision / Recall / F1)
     - 按 bbox 中心点最近距离贪心一一匹配
       （tag 也是被评估字段，不能用作匹配键；bbox 中心点是稳定的位置先验）
     - 设置距离阈值 `match_max_distance`，超出阈值不视为匹配
  2. bbox 准确率
     - 仅对匹配上的设备：平均 IoU、IoU≥阈值 命中率（默认 0.5）
  3. tag 准确率（完全匹配率，不归一化）
  4. equipment_type 准确率（完全匹配率）
  5. 端口 direction / category 准确率
     - 仅对匹配上的设备：端口按 position 做最近邻一一对齐
       * 若 label 端口缺少 position：退化为按 direction 分组、按出现顺序对齐
     - 对齐后比较 direction 与 category 字段
     - 端口数量差异计入 port FP / FN（影响 port F1）

设计原则（遵守 TRAE 研发铁律）：
  - 问题驱动：用 P/R/F1 + IoU 等可量化指标说明专家提取质量
  - 可验证：所有指标都有明细列表，可定位到具体设备/端口
  - 数据驱动：避免任何"看上去差不多"的主观判断，全部基于位置距离/字段比较
  - 边界清晰：当 label 缺位置时退化为顺序对齐，并在报告中标识该退化
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from .metrics import MetricSet


# ---------------------------------------------------------------------------
# Geometric helpers
# ---------------------------------------------------------------------------


def _bbox_iou(a: list[float], b: list[float]) -> float:
    """计算两个 bbox 的 IoU。bbox 格式: [x_min, y_min, x_max, y_max]。"""
    if not (a and b) or len(a) < 4 or len(b) < 4:
        return 0.0
    ax1, ay1, ax2, ay2 = a[:4]
    bx1, by1, bx2, by2 = b[:4]
    # 归一化（防止反向）
    ax1, ax2 = min(ax1, ax2), max(ax1, ax2)
    ay1, ay2 = min(ay1, ay2), max(ay1, ay2)
    bx1, bx2 = min(bx1, bx2), max(bx1, bx2)
    by1, by2 = min(by1, by2), max(by1, by2)

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    iw = max(0.0, inter_x2 - inter_x1)
    ih = max(0.0, inter_y2 - inter_y1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _bbox_center(b: list[float]) -> Optional[tuple[float, float]]:
    if not b or len(b) < 4:
        return None
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def _euclid(p: tuple[float, float], q: tuple[float, float]) -> float:
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


# ---------------------------------------------------------------------------
# Port pairing
# ---------------------------------------------------------------------------


def _port_position(port: dict[str, Any]) -> Optional[tuple[float, float]]:
    pos = port.get("position")
    if isinstance(pos, (list, tuple)) and len(pos) >= 2:
        try:
            return float(pos[0]), float(pos[1])
        except (TypeError, ValueError):
            return None
    return None


def _greedy_nearest_pairing(
    label_ports: list[dict[str, Any]],
    extraction_ports: list[dict[str, Any]],
) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
    """基于位置最近邻的贪心一一匹配。

    返回:
        matched: [(label_idx, extraction_idx, distance), ...]
        unmatched_label_idx: list[int]
        unmatched_extraction_idx: list[int]

    若任一侧端口缺位置，会被排除在按位置匹配之外，留作未匹配返回。
    """
    label_with_pos = [(i, _port_position(p)) for i, p in enumerate(label_ports)]
    ext_with_pos = [(i, _port_position(p)) for i, p in enumerate(extraction_ports)]

    label_pos = [(i, pos) for i, pos in label_with_pos if pos is not None]
    ext_pos = [(i, pos) for i, pos in ext_with_pos if pos is not None]

    # 计算所有 pair 距离并按升序排序，贪心选取
    pairs: list[tuple[float, int, int]] = []
    for li, lp in label_pos:
        for ei, ep in ext_pos:
            pairs.append((_euclid(lp, ep), li, ei))
    pairs.sort(key=lambda x: x[0])

    used_label: set[int] = set()
    used_ext: set[int] = set()
    matched: list[tuple[int, int, float]] = []
    for dist, li, ei in pairs:
        if li in used_label or ei in used_ext:
            continue
        matched.append((li, ei, dist))
        used_label.add(li)
        used_ext.add(ei)

    unmatched_label = [i for i, _ in enumerate(label_ports) if i not in used_label]
    unmatched_ext = [i for i, _ in enumerate(extraction_ports) if i not in used_ext]
    return matched, unmatched_label, unmatched_ext


def _ordered_pairing_by_direction(
    label_ports: list[dict[str, Any]],
    extraction_ports: list[dict[str, Any]],
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """退化策略：当 label 端口缺位置时，按 direction 分组、按列表顺序对齐。"""
    # 按 direction 分组保留原始 index
    def _group(ports: list[dict[str, Any]]) -> dict[str, list[int]]:
        g: dict[str, list[int]] = {}
        for i, p in enumerate(ports):
            d = (p.get("direction") or "unknown").lower()
            g.setdefault(d, []).append(i)
        return g

    g_label = _group(label_ports)
    g_ext = _group(extraction_ports)

    matched: list[tuple[int, int]] = []
    used_label: set[int] = set()
    used_ext: set[int] = set()
    for direction, l_idx_list in g_label.items():
        e_idx_list = g_ext.get(direction, [])
        for li, ei in zip(l_idx_list, e_idx_list):
            matched.append((li, ei))
            used_label.add(li)
            used_ext.add(ei)

    unmatched_label = [i for i in range(len(label_ports)) if i not in used_label]
    unmatched_ext = [i for i in range(len(extraction_ports)) if i not in used_ext]
    return matched, unmatched_label, unmatched_ext


# ---------------------------------------------------------------------------
# Per-equipment evaluation
# ---------------------------------------------------------------------------


@dataclass
class PortPairDiff:
    label_port_id: str
    extraction_port_id: str
    direction_label: str
    direction_extraction: str
    category_label: str
    category_extraction: str
    direction_match: bool
    category_match: bool
    distance: Optional[float] = None


@dataclass
class EquipmentDiff:
    """单台匹配设备的字段对比明细。"""

    label_id: str
    extraction_id: str
    tag_label: str
    tag_extraction: str
    tag_match: bool
    center_distance: float
    bbox_iou: float
    bbox_hit_threshold: bool
    equipment_type_label: str
    equipment_type_extraction: str
    equipment_type_match: bool
    port_label_count: int
    port_extraction_count: int
    port_pairs: list[PortPairDiff] = field(default_factory=list)
    port_unmatched_label: list[str] = field(default_factory=list)
    port_unmatched_extraction: list[str] = field(default_factory=list)
    port_pairing_strategy: str = "nearest_position"  # or "ordered_by_direction"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class EquipmentEvaluationReport:
    sample_id: str = ""
    bbox_iou_threshold: float = 0.5
    match_max_distance: float = 0.1  # 中心点距离阈值（归一化坐标）

    # 1. 设备识别
    equipment_metric: MetricSet = field(default_factory=MetricSet)
    label_unmatched: list[str] = field(default_factory=list)  # tag/name/id
    extraction_unmatched: list[str] = field(default_factory=list)

    # 字段对比明细
    diffs: list[EquipmentDiff] = field(default_factory=list)

    # 聚合
    bbox_mean_iou: float = 0.0
    bbox_hit_rate: float = 0.0
    tag_accuracy: float = 0.0
    equipment_type_accuracy: float = 0.0
    port_direction_metric: MetricSet = field(default_factory=MetricSet)
    port_category_metric: MetricSet = field(default_factory=MetricSet)
    # 端口数量本身的 P/R/F1（FP=多预测，FN=漏预测）
    port_count_metric: MetricSet = field(default_factory=MetricSet)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "bbox_iou_threshold": self.bbox_iou_threshold,
            "match_max_distance": self.match_max_distance,
            "equipment_detection": self.equipment_metric.as_dict(),
            "bbox": {
                "mean_iou": round(self.bbox_mean_iou, 4),
                "hit_rate": round(self.bbox_hit_rate, 4),
                "iou_threshold": self.bbox_iou_threshold,
            },
            "tag_accuracy": round(self.tag_accuracy, 4),
            "equipment_type_accuracy": round(self.equipment_type_accuracy, 4),
            "port_direction": self.port_direction_metric.as_dict(),
            "port_category": self.port_category_metric.as_dict(),
            "port_count": self.port_count_metric.as_dict(),
            "label_unmatched": self.label_unmatched,
            "extraction_unmatched": self.extraction_unmatched,
            "details": [
                {
                    "label_id": d.label_id,
                    "extraction_id": d.extraction_id,
                    "tag": {
                        "label": d.tag_label,
                        "extraction": d.tag_extraction,
                        "match": d.tag_match,
                    },
                    "center_distance": round(d.center_distance, 4),
                    "bbox_iou": round(d.bbox_iou, 4),
                    "bbox_hit": d.bbox_hit_threshold,
                    "equipment_type": {
                        "label": d.equipment_type_label,
                        "extraction": d.equipment_type_extraction,
                        "match": d.equipment_type_match,
                    },
                    "port_pairing_strategy": d.port_pairing_strategy,
                    "port_counts": {
                        "label": d.port_label_count,
                        "extraction": d.port_extraction_count,
                    },
                    "port_pairs": [
                        {
                            "label_port_id": pp.label_port_id,
                            "extraction_port_id": pp.extraction_port_id,
                            "direction": {
                                "label": pp.direction_label,
                                "extraction": pp.direction_extraction,
                                "match": pp.direction_match,
                            },
                            "category": {
                                "label": pp.category_label,
                                "extraction": pp.category_extraction,
                                "match": pp.category_match,
                            },
                            "distance": (
                                round(pp.distance, 4) if pp.distance is not None else None
                            ),
                        }
                        for pp in d.port_pairs
                    ],
                    "port_unmatched_label": d.port_unmatched_label,
                    "port_unmatched_extraction": d.port_unmatched_extraction,
                }
                for d in self.diffs
            ],
        }

    def print_summary(self) -> None:
        print(f"\n{'=' * 70}")
        print(f"Equipment Extraction Evaluation - Sample: {self.sample_id}")
        print(f"{'=' * 70}")

        m = self.equipment_metric
        print("\n[1] Equipment Detection (bbox center nearest, "
              f"max dist={self.match_max_distance})")
        print(f"    TP={m.tp}  FP={m.fp}  FN={m.fn}")
        print(f"    Precision: {m.precision:.4f}  Recall: {m.recall:.4f}  F1: {m.f1:.4f}")

        print("\n[2] BBox Accuracy (on matched equipments)")
        print(f"    Mean IoU: {self.bbox_mean_iou:.4f}")
        print(
            f"    Hit rate (IoU >= {self.bbox_iou_threshold}): "
            f"{self.bbox_hit_rate:.4f}"
        )

        print("\n[3] tag Accuracy (on matched equipments)")
        print(f"    Accuracy: {self.tag_accuracy:.4f}")

        print("\n[4] equipment_type Accuracy (on matched equipments)")
        print(f"    Accuracy: {self.equipment_type_accuracy:.4f}")

        pd_ = self.port_direction_metric
        pc_ = self.port_category_metric
        pn_ = self.port_count_metric
        print("\n[5] Port Field Accuracy (on matched equipments)")
        print(
            f"    Direction  -> P: {pd_.precision:.4f}  R: {pd_.recall:.4f}  "
            f"F1: {pd_.f1:.4f}  (TP={pd_.tp} FP={pd_.fp} FN={pd_.fn})"
        )
        print(
            f"    Category   -> P: {pc_.precision:.4f}  R: {pc_.recall:.4f}  "
            f"F1: {pc_.f1:.4f}  (TP={pc_.tp} FP={pc_.fp} FN={pc_.fn})"
        )
        print(
            f"    Port count -> P: {pn_.precision:.4f}  R: {pn_.recall:.4f}  "
            f"F1: {pn_.f1:.4f}  (TP={pn_.tp} FP={pn_.fp} FN={pn_.fn})"
        )

        if self.label_unmatched:
            print("\n[Unmatched label equipments (FN)]")
            for t in self.label_unmatched:
                print(f"  - {t}")
        if self.extraction_unmatched:
            print("\n[Unmatched extraction equipments (FP)]")
            for t in self.extraction_unmatched:
                print(f"  - {t}")
        print(f"\n{'=' * 70}")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_label_equipment(label_path: Union[str, Path]) -> list[dict[str, Any]]:
    with open(label_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("equipment_nodes", []) or [])


def _load_extraction_equipment(extraction_path: Union[str, Path]) -> list[dict[str, Any]]:
    with open(extraction_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 兼容 equipment.json (top-level "equipment") 和 equipment_result.json (top-level "data.equipment")
    if isinstance(data, dict):
        if "equipment" in data and isinstance(data["equipment"], list):
            return list(data["equipment"])
        if "data" in data and isinstance(data["data"], dict):
            inner = data["data"].get("equipment")
            if isinstance(inner, list):
                return list(inner)
    raise ValueError(
        f"Unsupported extraction format: {extraction_path}. "
        f"Expected top-level 'equipment' list or 'data.equipment'."
    )


# ---------------------------------------------------------------------------
# Core evaluator
# ---------------------------------------------------------------------------


class EquipmentEvaluator:
    """装置级设备节点提取评估器。

    Usage:
        evaluator = EquipmentEvaluator()
        report = evaluator.evaluate(
            label_path="data/label/001.json",
            extraction_path="output/equipment_nodes/equipment.json",
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
    ) -> EquipmentEvaluationReport:
        label_eqs = _load_label_equipment(label_path)
        ext_eqs = _load_extraction_equipment(extraction_path)
        return self.evaluate_from_lists(label_eqs, ext_eqs, sample_id=sample_id)

    def evaluate_from_lists(
        self,
        label_equipments: list[dict[str, Any]],
        extraction_equipments: list[dict[str, Any]],
        sample_id: str = "",
    ) -> EquipmentEvaluationReport:
        report = EquipmentEvaluationReport(
            sample_id=sample_id,
            bbox_iou_threshold=self.bbox_iou_threshold,
            match_max_distance=self.match_max_distance,
        )

        # 1) 设备匹配（bbox 中心点最近贪心）
        matched_pairs, unmatched_label, unmatched_ext = self._match_equipments(
            label_equipments, extraction_equipments
        )
        report.equipment_metric = MetricSet(
            tp=len(matched_pairs),
            fp=len(unmatched_ext),
            fn=len(unmatched_label),
        )
        report.label_unmatched = [
            (eq.get("tag") or eq.get("name") or eq.get("id") or "")
            for eq in unmatched_label
        ]
        report.extraction_unmatched = [
            (eq.get("tag") or eq.get("name") or eq.get("id") or "")
            for eq in unmatched_ext
        ]

        # 2-5) 仅对匹配设备做字段比对
        iou_list: list[float] = []
        hits = 0
        tag_correct = 0
        type_correct = 0
        port_dir = MetricSet()
        port_cat = MetricSet()
        port_cnt = MetricSet()

        for label_eq, ext_eq, dist in matched_pairs:
            diff = self._diff_equipment(label_eq, ext_eq, dist)
            report.diffs.append(diff)

            iou_list.append(diff.bbox_iou)
            if diff.bbox_hit_threshold:
                hits += 1
            if diff.tag_match:
                tag_correct += 1
            if diff.equipment_type_match:
                type_correct += 1

            # port 指标累计
            for pp in diff.port_pairs:
                if pp.direction_match:
                    port_dir.tp += 1
                else:
                    port_dir.fp += 1
                    port_dir.fn += 1
                if pp.category_match:
                    port_cat.tp += 1
                else:
                    port_cat.fp += 1
                    port_cat.fn += 1
            port_cnt.tp += len(diff.port_pairs)
            port_cnt.fp += len(diff.port_unmatched_extraction)
            port_cnt.fn += len(diff.port_unmatched_label)
            port_dir.fp += len(diff.port_unmatched_extraction)
            port_dir.fn += len(diff.port_unmatched_label)
            port_cat.fp += len(diff.port_unmatched_extraction)
            port_cat.fn += len(diff.port_unmatched_label)

        n_matched = len(matched_pairs)
        report.bbox_mean_iou = sum(iou_list) / n_matched if n_matched else 0.0
        report.bbox_hit_rate = hits / n_matched if n_matched else 0.0
        report.tag_accuracy = tag_correct / n_matched if n_matched else 0.0
        report.equipment_type_accuracy = type_correct / n_matched if n_matched else 0.0
        report.port_direction_metric = port_dir
        report.port_category_metric = port_cat
        report.port_count_metric = port_cnt

        return report

    # --- internal helpers ---

    def _match_equipments(
        self,
        label_eqs: list[dict[str, Any]],
        ext_eqs: list[dict[str, Any]],
    ) -> tuple[
        list[tuple[dict[str, Any], dict[str, Any], float]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """按 bbox 中心点最近距离贪心一一匹配。

        距离超过 `match_max_distance` 的对不视为匹配。
        """
        pairs: list[tuple[float, int, int]] = []
        for li, leq in enumerate(label_eqs):
            lcenter = _bbox_center(leq.get("bbox") or [])
            if lcenter is None:
                continue
            for ei, eeq in enumerate(ext_eqs):
                ecenter = _bbox_center(eeq.get("bbox") or [])
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
            matched.append((label_eqs[li], ext_eqs[ei], dist))
            used_label.add(li)
            used_ext.add(ei)

        unmatched_label = [label_eqs[i] for i in range(len(label_eqs)) if i not in used_label]
        unmatched_ext = [ext_eqs[j] for j in range(len(ext_eqs)) if j not in used_ext]
        return matched, unmatched_label, unmatched_ext

    def _diff_equipment(
        self,
        label_eq: dict[str, Any],
        ext_eq: dict[str, Any],
        center_distance: float,
    ) -> EquipmentDiff:
        # bbox / tag / equipment_type
        iou = _bbox_iou(label_eq.get("bbox") or [], ext_eq.get("bbox") or [])
        tag_l = (label_eq.get("tag") or "")
        tag_e = (ext_eq.get("tag") or "")
        type_l = (label_eq.get("equipment_type") or "").strip()
        type_e = (ext_eq.get("equipment_type") or "").strip()

        diff = EquipmentDiff(
            label_id=label_eq.get("id", ""),
            extraction_id=ext_eq.get("id", ""),
            tag_label=tag_l,
            tag_extraction=tag_e,
            tag_match=(tag_l == tag_e and tag_l != ""),
            center_distance=center_distance,
            bbox_iou=iou,
            bbox_hit_threshold=iou >= self.bbox_iou_threshold,
            equipment_type_label=type_l,
            equipment_type_extraction=type_e,
            equipment_type_match=(type_l == type_e and type_l != ""),
            port_label_count=len(label_eq.get("ports") or []),
            port_extraction_count=len(ext_eq.get("ports") or []),
        )

        label_ports = list(label_eq.get("ports") or [])
        ext_ports = list(ext_eq.get("ports") or [])

        # 决定端口配对策略
        label_has_pos = any(_port_position(p) is not None for p in label_ports)
        if label_has_pos:
            diff.port_pairing_strategy = "nearest_position"
            matched, unm_l, unm_e = _greedy_nearest_pairing(label_ports, ext_ports)
            for li, ei, dist in matched:
                lp = label_ports[li]
                ep = ext_ports[ei]
                diff.port_pairs.append(self._build_port_pair(lp, ep, distance=dist))
            diff.port_unmatched_label = [
                (label_ports[i].get("id") or f"label_port_{i}") for i in unm_l
            ]
            diff.port_unmatched_extraction = [
                (ext_ports[i].get("id") or f"ext_port_{i}") for i in unm_e
            ]
        else:
            diff.port_pairing_strategy = "ordered_by_direction"
            matched_idx, unm_l, unm_e = _ordered_pairing_by_direction(
                label_ports, ext_ports
            )
            for li, ei in matched_idx:
                lp = label_ports[li]
                ep = ext_ports[ei]
                diff.port_pairs.append(self._build_port_pair(lp, ep, distance=None))
            diff.port_unmatched_label = [
                (label_ports[i].get("id") or f"label_port_{i}") for i in unm_l
            ]
            diff.port_unmatched_extraction = [
                (ext_ports[i].get("id") or f"ext_port_{i}") for i in unm_e
            ]

        return diff

    @staticmethod
    def _build_port_pair(
        label_port: dict[str, Any],
        ext_port: dict[str, Any],
        distance: Optional[float],
    ) -> PortPairDiff:
        dl = (label_port.get("direction") or "").strip().lower()
        de = (ext_port.get("direction") or "").strip().lower()
        cl = (label_port.get("category") or "").strip().lower()
        ce = (ext_port.get("category") or "").strip().lower()
        return PortPairDiff(
            label_port_id=label_port.get("id", ""),
            extraction_port_id=ext_port.get("id", ""),
            direction_label=dl,
            direction_extraction=de,
            category_label=cl,
            category_extraction=ce,
            direction_match=(dl == de and dl != ""),
            category_match=(cl == ce and cl != ""),
            distance=distance,
        )


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def evaluate_equipment_sample(
    sample_id: str,
    label_dir: Union[str, Path] = "data/label",
    extraction_path: Union[str, Path, None] = None,
    bbox_iou_threshold: float = 0.5,
    match_max_distance: float = 0.1,
) -> EquipmentEvaluationReport:
    """按 sample_id 评估一个样本。

    默认路径:
      label:      {label_dir}/{sample_id}.json
      extraction: output/equipment_nodes/equipment.json
    """
    label_path = Path(label_dir) / f"{sample_id}.json"
    if extraction_path is None:
        extraction_path = Path("output/equipment_nodes/equipment.json")
    if not label_path.exists():
        raise FileNotFoundError(f"Label file not found: {label_path}")
    if not Path(extraction_path).exists():
        raise FileNotFoundError(f"Extraction file not found: {extraction_path}")
    evaluator = EquipmentEvaluator(
        bbox_iou_threshold=bbox_iou_threshold,
        match_max_distance=match_max_distance,
    )
    return evaluator.evaluate(label_path, extraction_path, sample_id=sample_id)
