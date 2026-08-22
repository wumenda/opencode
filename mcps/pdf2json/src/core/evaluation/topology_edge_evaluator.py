"""TopologyExpert 拓扑边连接准确率评估算法。

输入：
  - label       : data/label/{id}.json (含 equipment_nodes/boundary_nodes/edges)
  - extraction  : output/topology_standalone/topology.json (同结构)

评估目标：
  - 仅评估"节点之间边的连接准确率"（连对了多少 / 连错了多少 / 漏了多少）
  - 不评估 stream_name / medium / condition 等字段

评估流程：
  1. 节点对齐：equipment 按 bbox 中心点最近匹配；boundary 按 bbox 中心点最近匹配
     （两边的 node id 体系完全独立，必须先对齐）
  2. 边规范化：把每条边的 source_node_id/target_node_id 通过对齐映射换成 label 端 id
  3. 边集合比较：
     - directed   : (src, tgt) 严格方向
     - undirected : frozenset({src, tgt}) 忽略方向
  4. 指标：Precision / Recall / F1（TP/FP/FN），directed 与 undirected 两套

设计原则：
  - 问题驱动：评估 standalone TopologyExpert 的核心能力——"谁连到谁"
  - 数据驱动：用集合运算精确算出 TP/FP/FN，不依赖主观判断
  - 可验证：输出 matched/missing/extra 明细，可定位到具体边
  - 边界清晰：含未对齐节点的边单独报告，不计入主指标（避免节点对齐误差污染边指标）
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


def _bbox_center(b: list[float] | None) -> Optional[tuple[float, float]]:
    if not b or len(b) < 4:
        return None
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def _euclid(p: tuple[float, float], q: tuple[float, float]) -> float:
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


def _match_nodes_by_bbox(
    label_nodes: list[dict[str, Any]],
    ext_nodes: list[dict[str, Any]],
    max_distance: float,
) -> tuple[dict[str, str], list[str], list[str]]:
    """按 bbox 中心点最近距离贪心一一匹配。

    Returns:
        id_map: label_id -> ext_id  (仅含匹配成功的)
        unmatched_label_ids: list[str]
        unmatched_ext_ids: list[str]
    """
    # 计算所有 pair 距离，过滤超过阈值的
    pairs: list[tuple[float, int, int]] = []
    for li, ln in enumerate(label_nodes):
        lc = _bbox_center(ln.get("bbox"))
        if lc is None:
            continue
        for ei, en in enumerate(ext_nodes):
            ec = _bbox_center(en.get("bbox"))
            if ec is None:
                continue
            dist = _euclid(lc, ec)
            if dist <= max_distance:
                pairs.append((dist, li, ei))
    pairs.sort(key=lambda x: x[0])

    used_label: set[int] = set()
    used_ext: set[int] = set()
    id_map: dict[str, str] = {}
    for _, li, ei in pairs:
        if li in used_label or ei in used_ext:
            continue
        lid = label_nodes[li].get("id", "")
        eid = ext_nodes[ei].get("id", "")
        if lid and eid:
            id_map[lid] = eid
            used_label.add(li)
            used_ext.add(ei)

    unmatched_label = [
        label_nodes[i].get("id", f"label_{i}")
        for i in range(len(label_nodes))
        if i not in used_label
    ]
    unmatched_ext = [
        ext_nodes[j].get("id", f"ext_{j}")
        for j in range(len(ext_nodes))
        if j not in used_ext
    ]
    return id_map, unmatched_label, unmatched_ext


# ---------------------------------------------------------------------------
# Report data classes
# ---------------------------------------------------------------------------


@dataclass
class EdgeMatchDetail:
    """单条边的匹配明细。"""
    edge_id: str
    source_key: str
    target_key: str
    stream_name: str = ""


@dataclass
class TopologyEdgeReport:
    sample_id: str = ""
    match_max_distance: float = 0.1

    # 节点对齐
    equipment_alignment: dict[str, str] = field(default_factory=dict)  # label_id -> ext_id
    boundary_alignment: dict[str, str] = field(default_factory=dict)
    unmatched_equipment_label: list[str] = field(default_factory=list)
    unmatched_equipment_ext: list[str] = field(default_factory=list)
    unmatched_boundary_label: list[str] = field(default_factory=list)
    unmatched_boundary_ext: list[str] = field(default_factory=list)

    # 边数量
    label_edge_count: int = 0
    extraction_edge_count: int = 0
    unmatched_endpoint_edge_count: int = 0  # 含未对齐节点的边（排除在主指标外）

    # 边指标
    directed_metric: MetricSet = field(default_factory=MetricSet)
    undirected_metric: MetricSet = field(default_factory=MetricSet)

    # 边明细
    matched_directed: list[EdgeMatchDetail] = field(default_factory=list)
    missing_directed: list[EdgeMatchDetail] = field(default_factory=list)   # FN
    extra_directed: list[EdgeMatchDetail] = field(default_factory=list)      # FP
    direction_flipped: list[EdgeMatchDetail] = field(default_factory=list)   # undirected 匹配但方向反了
    unmatched_endpoint_edges: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "match_max_distance": self.match_max_distance,
            "node_alignment": {
                "equipment": {
                    "matched": [
                        {"label_id": k, "extraction_id": v}
                        for k, v in self.equipment_alignment.items()
                    ],
                    "unmatched_label": self.unmatched_equipment_label,
                    "unmatched_ext": self.unmatched_equipment_ext,
                },
                "boundary": {
                    "matched": [
                        {"label_id": k, "extraction_id": v}
                        for k, v in self.boundary_alignment.items()
                    ],
                    "unmatched_label": self.unmatched_boundary_label,
                    "unmatched_ext": self.unmatched_boundary_ext,
                },
            },
            "edge_counts": {
                "label": self.label_edge_count,
                "extraction": self.extraction_edge_count,
                "unmatched_endpoint": self.unmatched_endpoint_edge_count,
            },
            "directed": self.directed_metric.as_dict(),
            "undirected": self.undirected_metric.as_dict(),
            "details": {
                "matched_directed": [
                    {"edge_id": e.edge_id, "source": e.source_key, "target": e.target_key,
                     "stream_name": e.stream_name}
                    for e in self.matched_directed
                ],
                "missing_directed": [
                    {"edge_id": e.edge_id, "source": e.source_key, "target": e.target_key,
                     "stream_name": e.stream_name}
                    for e in self.missing_directed
                ],
                "extra_directed": [
                    {"edge_id": e.edge_id, "source": e.source_key, "target": e.target_key,
                     "stream_name": e.stream_name}
                    for e in self.extra_directed
                ],
                "direction_flipped": [
                    {"edge_id": e.edge_id, "source": e.source_key, "target": e.target_key,
                     "stream_name": e.stream_name}
                    for e in self.direction_flipped
                ],
                "unmatched_endpoint_edges": self.unmatched_endpoint_edges,
            },
        }

    def print_summary(self) -> None:
        print(f"\n{'=' * 70}")
        print(f"Topology Edge Evaluation - Sample: {self.sample_id}")
        print(f"{'=' * 70}")

        print(f"\n[Node Alignment (bbox center nearest, max dist={self.match_max_distance})]")
        print(f"    Equipment matched: {len(self.equipment_alignment)}  "
              f"label_unmatched: {len(self.unmatched_equipment_label)}  "
              f"ext_unmatched: {len(self.unmatched_equipment_ext)}")
        print(f"    Boundary  matched: {len(self.boundary_alignment)}  "
              f"label_unmatched: {len(self.unmatched_boundary_label)}  "
              f"ext_unmatched: {len(self.unmatched_boundary_ext)}")

        print("\n[Edge Counts]")
        print(f"    Label edges:      {self.label_edge_count}")
        print(f"    Extraction edges: {self.extraction_edge_count}")
        print(f"    Unmatched-endpoint edges (excluded): {self.unmatched_endpoint_edge_count}")

        dm = self.directed_metric
        um = self.undirected_metric
        print("\n[Directed Edge Accuracy]")
        print(f"    TP={dm.tp}  FP={dm.fp}  FN={dm.fn}")
        print(f"    Precision: {dm.precision:.4f}  Recall: {dm.recall:.4f}  F1: {dm.f1:.4f}")

        print("\n[Undirected Edge Accuracy (direction ignored)]")
        print(f"    TP={um.tp}  FP={um.fp}  FN={um.fn}")
        print(f"    Precision: {um.precision:.4f}  Recall: {um.recall:.4f}  F1: {um.f1:.4f}")

        if self.direction_flipped:
            print(f"\n[Direction Flipped ({len(self.direction_flipped)})]")
            for e in self.direction_flipped[:10]:
                print(f"  - {e.edge_id}: {e.source_key} -> {e.target_key}  ({e.stream_name})")
            if len(self.direction_flipped) > 10:
                print(f"  ... and {len(self.direction_flipped) - 10} more")

        if self.missing_directed:
            print("\n[Missing Edges (FN - in label, not in extraction)]")
            for e in self.missing_directed[:10]:
                print(f"  - {e.edge_id}: {e.source_key} -> {e.target_key}  ({e.stream_name})")
            if len(self.missing_directed) > 10:
                print(f"  ... and {len(self.missing_directed) - 10} more")

        if self.extra_directed:
            print("\n[Extra Edges (FP - in extraction, not in label)]")
            for e in self.extra_directed[:10]:
                print(f"  - {e.edge_id}: {e.source_key} -> {e.target_key}  ({e.stream_name})")
            if len(self.extra_directed) > 10:
                print(f"  ... and {len(self.extra_directed) - 10} more")

        if self.unmatched_endpoint_edges:
            print("\n[Unmatched-Endpoint Edges (cannot evaluate)]")
            for e in self.unmatched_endpoint_edges[:5]:
                print(f"  - {e.get('edge_id', '')}: {e.get('source', '')} -> {e.get('target', '')} "
                      f"(side={e.get('side', '')})")
            if len(self.unmatched_endpoint_edges) > 5:
                print(f"  ... and {len(self.unmatched_endpoint_edges) - 5} more")

        print(f"\n{'=' * 70}")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_topology(path: Union[str, Path]) -> tuple[list[dict], list[dict], list[dict]]:
    """加载 topology JSON，返回 (equipment_nodes, boundary_nodes, edges)。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    eqs = list(data.get("equipment_nodes", []) or [])
    bns = list(data.get("boundary_nodes", []) or [])
    edges = list(data.get("edges", []) or [])
    return eqs, bns, edges


# ---------------------------------------------------------------------------
# Core evaluator
# ---------------------------------------------------------------------------


class TopologyEdgeEvaluator:
    """拓扑边连接准确率评估器。

    Usage:
        evaluator = TopologyEdgeEvaluator()
        report = evaluator.evaluate(
            label_path="data/label/001.json",
            extraction_path="output/topology_standalone/topology.json",
            sample_id="001",
        )
        report.print_summary()
    """

    def __init__(self, match_max_distance: float = 0.1) -> None:
        self.match_max_distance = match_max_distance

    def evaluate(
        self,
        label_path: Union[str, Path],
        extraction_path: Union[str, Path],
        sample_id: str = "",
    ) -> TopologyEdgeReport:
        l_eqs, l_bns, l_edges = _load_topology(label_path)
        e_eqs, e_bns, e_edges = _load_topology(extraction_path)
        return self.evaluate_from_lists(l_eqs, l_bns, l_edges, e_eqs, e_bns, e_edges, sample_id)

    def evaluate_from_lists(
        self,
        l_eqs: list[dict],
        l_bns: list[dict],
        l_edges: list[dict],
        e_eqs: list[dict],
        e_bns: list[dict],
        e_edges: list[dict],
        sample_id: str = "",
    ) -> TopologyEdgeReport:
        report = TopologyEdgeReport(
            sample_id=sample_id,
            match_max_distance=self.match_max_distance,
        )

        # 1) 节点对齐
        eq_map, eq_unm_l, eq_unm_e = _match_nodes_by_bbox(
            l_eqs, e_eqs, self.match_max_distance
        )
        bn_map, bn_unm_l, bn_unm_e = _match_nodes_by_bbox(
            l_bns, e_bns, self.match_max_distance
        )
        report.equipment_alignment = eq_map
        report.boundary_alignment = bn_map
        report.unmatched_equipment_label = eq_unm_l
        report.unmatched_equipment_ext = eq_unm_e
        report.unmatched_boundary_label = bn_unm_l
        report.unmatched_boundary_ext = bn_unm_e

        # 合并 label_id -> ext_id 映射
        full_map: dict[str, str] = {**eq_map, **bn_map}
        # 反向：ext_id -> label_id
        full_map_rev: dict[str, str] = {v: k for k, v in full_map.items()}

        # 2) 边规范化：把 ext 边的 node id 映射到 label 端 id
        #    label 边直接用自身 id（仅收集可评估边：两端都在 full_map 中）
        label_edge_set_dir: set[tuple[str, str]] = set()
        label_edge_map: dict[tuple[str, str], dict] = {}
        label_undirected_map: dict[frozenset, dict] = {}
        label_unmatched_endpoint: list[dict] = []
        for e in l_edges:
            src = e.get("source_node_id", "")
            tgt = e.get("target_node_id", "")
            if not src or not tgt:
                continue
            if src not in full_map or tgt not in full_map:
                label_unmatched_endpoint.append({
                    "edge_id": e.get("id", ""),
                    "source": src,
                    "target": tgt,
                    "side": "label",
                    "stream_name": e.get("stream_name", ""),
                })
                continue
            key = (src, tgt)
            label_edge_set_dir.add(key)
            label_edge_map[key] = e
            ukey = frozenset({src, tgt})
            if ukey not in label_undirected_map:
                label_undirected_map[ukey] = e

        ext_edge_set_dir: set[tuple[str, str]] = set()
        ext_edge_map: dict[tuple[str, str], dict] = {}
        ext_undirected_map: dict[frozenset, dict] = {}
        ext_unmatched_endpoint: list[dict] = []
        for e in e_edges:
            src_raw = e.get("source_node_id", "")
            tgt_raw = e.get("target_node_id", "")
            # 映射到 label 端 id
            src = full_map_rev.get(src_raw, "")
            tgt = full_map_rev.get(tgt_raw, "")
            if not src or not tgt:
                ext_unmatched_endpoint.append({
                    "edge_id": e.get("id", ""),
                    "source": src_raw,
                    "target": tgt_raw,
                    "side": "extraction",
                    "stream_name": e.get("stream_name", ""),
                })
                continue
            key = (src, tgt)
            ext_edge_set_dir.add(key)
            ext_edge_map[key] = e
            ukey = frozenset({src, tgt})
            if ukey not in ext_undirected_map:
                ext_undirected_map[ukey] = e

        report.label_edge_count = len(l_edges)
        report.extraction_edge_count = len(e_edges)
        report.unmatched_endpoint_edge_count = len(ext_unmatched_endpoint) + len(label_unmatched_endpoint)
        report.unmatched_endpoint_edges = ext_unmatched_endpoint + label_unmatched_endpoint

        # 3) Directed 比较
        matched_dir = label_edge_set_dir & ext_edge_set_dir
        missing_dir = label_edge_set_dir - ext_edge_set_dir   # FN
        extra_dir = ext_edge_set_dir - label_edge_set_dir      # FP

        for pair in sorted(matched_dir):
            e = label_edge_map[pair]
            report.matched_directed.append(EdgeMatchDetail(
                edge_id=e.get("id", ""),
                source_key=pair[0],
                target_key=pair[1],
                stream_name=e.get("stream_name", ""),
            ))
        for pair in sorted(missing_dir):
            e = label_edge_map[pair]
            report.missing_directed.append(EdgeMatchDetail(
                edge_id=e.get("id", ""),
                source_key=pair[0],
                target_key=pair[1],
                stream_name=e.get("stream_name", ""),
            ))
        for pair in sorted(extra_dir):
            e = ext_edge_map[pair]
            report.extra_directed.append(EdgeMatchDetail(
                edge_id=e.get("id", ""),
                source_key=pair[0],
                target_key=pair[1],
                stream_name=e.get("stream_name", ""),
            ))

        report.directed_metric = MetricSet(
            tp=len(matched_dir),
            fp=len(extra_dir),
            fn=len(missing_dir),
        )

        # 4) Undirected 比较
        label_undir_keys = set(label_undirected_map.keys())
        ext_undir_keys = set(ext_undirected_map.keys())
        matched_undir = label_undir_keys & ext_undir_keys
        missing_undir = label_undir_keys - ext_undir_keys
        extra_undir = ext_undir_keys - label_undir_keys

        report.undirected_metric = MetricSet(
            tp=len(matched_undir),
            fp=len(extra_undir),
            fn=len(missing_undir),
        )

        # 5) 方向反转：undirected 匹配但 directed 不匹配
        for ukey in sorted(matched_undir, key=lambda k: sorted(k)):
            l_edge = label_undirected_map[ukey]
            # 检查 (src, tgt) 是否在 matched_dir 中
            l_pair = (l_edge.get("source_node_id", ""), l_edge.get("target_node_id", ""))
            if l_pair not in matched_dir:
                # 检查是否是方向反转
                rev_pair = (l_pair[1], l_pair[0])
                if rev_pair in ext_edge_set_dir:
                    report.direction_flipped.append(EdgeMatchDetail(
                        edge_id=l_edge.get("id", ""),
                        source_key=l_pair[0],
                        target_key=l_pair[1],
                        stream_name=l_edge.get("stream_name", ""),
                    ))

        return report


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def evaluate_topology_edge_sample(
    sample_id: str,
    label_dir: Union[str, Path] = "data/label",
    extraction_path: Union[str, Path, None] = None,
    match_max_distance: float = 0.1,
) -> TopologyEdgeReport:
    """按 sample_id 评估拓扑边连接准确率。

    默认路径:
      label:      {label_dir}/{sample_id}.json
      extraction: output/topology_standalone/topology.json
    """
    label_path = Path(label_dir) / f"{sample_id}.json"
    if extraction_path is None:
        extraction_path = Path("output/topology_standalone/topology.json")
    if not label_path.exists():
        raise FileNotFoundError(f"Label file not found: {label_path}")
    if not Path(extraction_path).exists():
        raise FileNotFoundError(f"Extraction file not found: {extraction_path}")
    evaluator = TopologyEdgeEvaluator(match_max_distance=match_max_distance)
    return evaluator.evaluate(label_path, extraction_path, sample_id=sample_id)
