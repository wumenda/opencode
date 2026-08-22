"""Topology Overlay Workflow — 工艺说明拓扑与图纸设备节点匹配。

将工艺说明提取的拓扑（覆盖多张PFD图纸）与单张PFD图纸的设备节点 bbox 匹配，
生成该图纸的设备节点拓扑叠加视图。

匹配策略：
    1. 按 tag（位号）匹配工艺说明设备 → 图纸设备，建立 equip_id → node_id 映射
    2. 工艺说明中存在但图纸中未匹配到的设备 → 属于其他PFD图纸
    3. 连接关系处理：
       - 两端都在本图纸 → 直接生成 edge
       - 一端为 "external" → 生成 boundary_in/out 边界节点
       - 一端为跨图设备（未匹配到）→ 生成 cross_drawing_in/out 边界节点
       - 两端都不在本图纸 → 丢弃
    4. 图纸中多提取的设备（工艺说明未提及）→ 作为独立节点显示（无连接边）
"""

from __future__ import annotations

import re
from typing import Any

from src.core import get_logger
from src.core.models import (
    BoundaryNode,
    BoundaryType,
    PFDEquipmentNode,
    PFDTopology,
    StreamEdge,
    DrawingDeserializer,
)

logger = get_logger(__name__)


# ===================== 工具函数 =====================

def _normalize_tag(tag: str) -> str:
    """标准化位号用于匹配：小写 + 去除空白/连字符/下划线。

    "V-81001" / "v 81001" / "V_81001" → "v81001"
    """
    return re.sub(r"[\s\-_/]", "", tag.strip().lower())


def _build_tag_index(equipment_list: list[dict]) -> dict[str, dict]:
    """构建 normalized_tag → equipment_dict 索引。"""
    index: dict[str, dict] = {}
    for eq in equipment_list:
        norm = _normalize_tag(eq.get("tag", ""))
        if norm and norm not in index:
            index[norm] = eq
    return index


def _extract_pd_topology(data: dict[str, Any]) -> dict[str, Any]:
    """从工艺说明拓扑 JSON 中提取拓扑 dict。

    支持两种格式：
      - 直接格式: {equipment, connections, ...}（process_description_topology.json）
      - 包装格式: {expert_outputs: {process_description_topology: {...}}}（result.json）
    """
    if "equipment" in data and "connections" in data:
        return data
    expert_outputs = data.get("expert_outputs", {})
    pd_topo = expert_outputs.get("process_description_topology", {})
    if isinstance(pd_topo, dict) and ("equipment" in pd_topo or "connections" in pd_topo):
        return pd_topo
    # 尝试 data 字段（ExpertOutput.model_dump 格式）
    if "data" in data and isinstance(data["data"], dict):
        return data["data"]
    return data


def _extract_equipment_list(data: dict[str, Any]) -> list[dict]:
    """从设备节点 JSON 中提取 equipment 列表。

    支持多种格式：
      - equipment.json: {equipment: [...]}
      - equipment_result.json: {data: {equipment: [...]}}
      - equipment_node_result.json: {expert_outputs: {equipment: {equipment: [...]}}}
    """
    if isinstance(data.get("equipment"), list):
        return data["equipment"]
    inner = data.get("data")
    if isinstance(inner, dict) and isinstance(inner.get("equipment"), list):
        return inner["equipment"]
    expert_outputs = data.get("expert_outputs", {})
    eq_expert = expert_outputs.get("equipment", {})
    if isinstance(eq_expert, dict):
        if isinstance(eq_expert.get("equipment"), list):
            return eq_expert["equipment"]
        inner2 = eq_expert.get("data")
        if isinstance(inner2, dict) and isinstance(inner2.get("equipment"), list):
            return inner2["equipment"]
    return []


# ===================== 核心匹配逻辑 =====================

def match_topology_to_drawing(
    pd_topology: dict[str, Any],
    image_equipment: list[dict[str, Any]],
) -> dict[str, Any]:
    """将工艺说明拓扑匹配到单张图纸的设备节点。

    Args:
        pd_topology: 工艺说明拓扑，含 equipment / connections / warnings。
        image_equipment: 图纸设备节点列表（含 bbox/position/ports）。

    Returns:
        dict 含：
          - topology: PFDTopology 模型
          - match_stats: 匹配统计
          - warnings: 警告信息
    """
    pd_equipment = pd_topology.get("equipment", [])
    pd_connections = pd_topology.get("connections", [])
    warnings: list[str] = list(pd_topology.get("warnings", []))

    # --- 1. 构建图纸设备 tag 索引，匹配 equip_id → image node_id ---
    img_tag_index = _build_tag_index(image_equipment)

    equip_to_node: dict[str, str] = {}
    unmatched_pd_eq: dict[str, dict] = {}

    for pd_eq in pd_equipment:
        eq_id = pd_eq.get("id", "")
        norm_tag = _normalize_tag(pd_eq.get("tag", ""))
        if norm_tag and norm_tag in img_tag_index:
            equip_to_node[eq_id] = img_tag_index[norm_tag].get("id", "")
        else:
            unmatched_pd_eq[eq_id] = pd_eq

    # --- 2. 构建 equipment_nodes（全部图纸设备，含多余设备） ---
    equipment_nodes: list[PFDEquipmentNode] = []
    node_bbox_index: dict[str, tuple] = {}  # node_id → bbox，供边界节点对齐 y 用
    for eq_dict in image_equipment:
        node = DrawingDeserializer.node_from_dict(
            eq_dict.get("id", ""), eq_dict
        )
        if isinstance(node, PFDEquipmentNode):
            equipment_nodes.append(node)
            if node.bbox:
                node_bbox_index[node.id] = node.bbox

    # --- 3. 遍历连接，构建 boundary_nodes 和 edges ---
    boundary_nodes: list[BoundaryNode] = []
    edges: list[StreamEdge] = []
    bn_counter = 0
    edge_counter = 0
    cross_bn_cache: dict[str, str] = {}  # f"{equip_id}_{in|out}" → bn_id
    dropped_count = 0
    # 追踪左右两侧已占用的 y 区间，防止边界节点重叠
    occupied_y: dict[str, list[tuple[float, float]]] = {"in": [], "out": []}

    for conn in pd_connections:
        src = conn.get("source", "")
        tgt = conn.get("target", "")
        material = conn.get("material_name", "")
        desc = conn.get("description", "")

        src_matched = src in equip_to_node
        tgt_matched = tgt in equip_to_node

        # 两端都不在本图纸 → 丢弃
        if not src_matched and not tgt_matched:
            dropped_count += 1
            continue

        # 解析 source 端点
        src_node_id, bn_counter = _resolve_endpoint(
            src, is_source=True,
            other_endpoint=tgt,
            equip_to_node=equip_to_node,
            node_bbox_index=node_bbox_index,
            unmatched_pd_eq=unmatched_pd_eq,
            cross_bn_cache=cross_bn_cache,
            boundary_nodes=boundary_nodes,
            bn_counter=bn_counter,
            material=material,
            desc=desc,
            occupied_y=occupied_y,
        )

        tgt_node_id, bn_counter = _resolve_endpoint(
            tgt, is_source=False,
            other_endpoint=src,
            equip_to_node=equip_to_node,
            node_bbox_index=node_bbox_index,
            unmatched_pd_eq=unmatched_pd_eq,
            cross_bn_cache=cross_bn_cache,
            boundary_nodes=boundary_nodes,
            bn_counter=bn_counter,
            material=material,
            desc=desc,
            occupied_y=occupied_y,
        )

        if not src_node_id or not tgt_node_id:
            warnings.append(f"跳过连接 {src}→{tgt}: 端点无法解析")
            dropped_count += 1
            continue

        edge_counter += 1
        edges.append(StreamEdge(
            id=f"edge_{edge_counter}",
            source_node_id=src_node_id,
            source_port_id="",
            target_node_id=tgt_node_id,
            target_port_id="",
            stream_name=material,
            medium=material,
            metadata={
                "description": desc,
                "source_ref": src,
                "target_ref": tgt,
            },
        ))

    # --- 4. 构建 PFDTopology ---
    topology = PFDTopology(
        equipment_nodes=equipment_nodes,
        boundary_nodes=boundary_nodes,
        edges=edges,
    )

    # --- 5. 统计与警告 ---
    matched_count = len(equip_to_node)
    unmatched_count = len(unmatched_pd_eq)
    total_pd_eq = len(pd_equipment)
    extra_img_count = len(image_equipment) - matched_count

    if unmatched_count > 0:
        unmatched_tags = [
            f"{eq.get('tag', eq.get('id', ''))}"
            for eq in unmatched_pd_eq.values()
        ]
        warnings.append(
            f"工艺说明中 {unmatched_count}/{total_pd_eq} 个设备未在本图纸中匹配到"
            f"（属于其他PFD图纸）: {', '.join(unmatched_tags[:10])}"
            + ("..." if len(unmatched_tags) > 10 else "")
        )
    if extra_img_count > 0:
        warnings.append(
            f"图纸中 {extra_img_count} 个设备未在工艺说明中提及（作为独立节点显示）"
        )

    logger.info(
        f"匹配完成: 工艺说明设备 {total_pd_eq} -> 匹配 {matched_count}, "
        f"跨图 {unmatched_count}, 图纸多余 {extra_img_count}; "
        f"连接 {len(pd_connections)} -> 生成 {len(edges)} 条边, 丢弃 {dropped_count}; "
        f"边界节点 {len(boundary_nodes)}"
    )

    # --- 6. 组装匹配明细（供前端 MatchRelationView 消费） ---
    matched_details: list[dict[str, Any]] = []
    for pd_eq in pd_equipment:
        eq_id = pd_eq.get("id", "")
        if eq_id in equip_to_node:
            img_node_id = equip_to_node[eq_id]
            img_tag = ""
            for img_eq in image_equipment:
                if img_eq.get("id") == img_node_id:
                    img_tag = img_eq.get("tag", "")
                    break
            matched_details.append({
                "pd_equipment_id": eq_id,
                "pd_tag": pd_eq.get("tag", ""),
                "image_node_id": img_node_id,
                "image_tag": img_tag,
            })

    unmatched_pd_details: list[dict[str, Any]] = []
    for eq_id, pd_eq in unmatched_pd_eq.items():
        unmatched_pd_details.append({
            "pd_equipment_id": eq_id,
            "pd_tag": pd_eq.get("tag", ""),
            "reason": "cross_drawing",
        })

    matched_node_ids = set(equip_to_node.values())
    extra_image_details: list[dict[str, Any]] = []
    for img_eq in image_equipment:
        if img_eq.get("id") not in matched_node_ids:
            extra_image_details.append({
                "image_node_id": img_eq.get("id", ""),
                "image_tag": img_eq.get("tag", ""),
            })

    return {
        "topology": topology,
        "match_stats": {
            "pd_equipment_total": total_pd_eq,
            "matched": matched_count,
            "unmatched_pd": unmatched_count,
            "image_equipment_total": len(image_equipment),
            "extra_image": extra_img_count,
            "boundary_nodes": len(boundary_nodes),
            "edges": len(edges),
            "connections_total": len(pd_connections),
            "connections_dropped": dropped_count,
        },
        "warnings": warnings,
        "match_details": {
            "matched": matched_details,
            "unmatched_pd": unmatched_pd_details,
            "extra_image": extra_image_details,
        },
    }


def _resolve_endpoint(
    endpoint: str,
    is_source: bool,
    other_endpoint: str,
    equip_to_node: dict[str, str],
    node_bbox_index: dict[str, tuple],
    unmatched_pd_eq: dict[str, dict],
    cross_bn_cache: dict[str, str],
    boundary_nodes: list[BoundaryNode],
    bn_counter: int,
    material: str,
    desc: str,
    occupied_y: dict[str, list[tuple[float, float]]],
) -> tuple[str | None, int]:
    """解析连接端点，返回 (node_id, new_bn_counter)。

    - 匹配到的设备 → 返回 image node_id
    - "external" → 新建 boundary_in/out 节点
    - 跨图设备（未匹配）→ 新建/复用 cross_drawing_in/out 节点

    边界节点的 bbox 放置在图纸边缘：
      - source 端（in）→ 左边缘 (x≈0)，y 对齐连接的 target 设备
      - target 端（out）→ 右边缘 (x≈1)，y 对齐连接的 source 设备
    y 坐标自动避开同侧已放置的节点，防止重叠。
    """
    # 匹配到的设备
    if endpoint in equip_to_node:
        return equip_to_node[endpoint], bn_counter

    side = "in" if is_source else "out"
    # 计算边界节点在边缘的 bbox（含防重叠调整）
    bn_bbox = _edge_bbox(is_source, other_endpoint, equip_to_node, node_bbox_index, occupied_y[side])

    # "external" → 边界节点（每条连接独立创建）
    if endpoint == "external":
        bn_counter += 1
        if is_source:
            bn_id = f"bn_ext_in_{bn_counter}"
            bn = BoundaryNode(
                id=bn_id,
                boundary_type=BoundaryType.BOUNDARY_IN,
                label=material or "界外输入",
                description=desc,
                bbox=bn_bbox,
            )
        else:
            bn_id = f"bn_ext_out_{bn_counter}"
            bn = BoundaryNode(
                id=bn_id,
                boundary_type=BoundaryType.BOUNDARY_OUT,
                label=material or "界外输出",
                description=desc,
                bbox=bn_bbox,
            )
        boundary_nodes.append(bn)
        return bn_id, bn_counter

    # 跨图设备 → cross_drawing 边界节点（按 equip_id+方向 去重）
    if endpoint in unmatched_pd_eq:
        direction = "in" if is_source else "out"
        cache_key = f"{endpoint}_{direction}"
        if cache_key in cross_bn_cache:
            return cross_bn_cache[cache_key], bn_counter

        bn_counter += 1
        if is_source:
            bn_id = f"bn_cross_in_{bn_counter}"
            btype = BoundaryType.CROSS_DRAWING_IN
        else:
            bn_id = f"bn_cross_out_{bn_counter}"
            btype = BoundaryType.CROSS_DRAWING_OUT

        pd_eq = unmatched_pd_eq[endpoint]
        tag = pd_eq.get("tag", "")
        name = pd_eq.get("name", "")
        label = f"{name} {tag}".strip() or tag or endpoint

        boundary_nodes.append(BoundaryNode(
            id=bn_id,
            boundary_type=btype,
            label=label,
            description=f"跨图设备: {label}",
            equipment_tag=[tag] if tag else [],
            bbox=bn_bbox,
        ))
        cross_bn_cache[cache_key] = bn_id
        return bn_id, bn_counter

    logger.warning(f"未知端点: {endpoint}")
    return None, bn_counter


_BN_SIZE = 0.02  # 边界节点归一化尺寸
_BN_MARGIN = 0.015  # 边缘空隙
_BN_GAP = 0.008  # 同侧节点间最小间距


def _edge_bbox(
    is_source: bool,
    other_endpoint: str,
    equip_to_node: dict[str, str],
    node_bbox_index: dict[str, tuple],
    occupied: list[tuple[float, float]],
) -> tuple[float, float, float, float]:
    """计算边界节点在图纸边缘的 bbox。

    source 端（in）→ 左边缘，target 端（out）→ 右边缘。
    y 坐标对齐连接的对端设备中心；无法获取时回退到图纸中央。
    与图纸边缘保持 _BN_MARGIN 空隙。
    y 坐标自动避开同侧已占用区间，防止节点重叠。
    """
    # 查找对端设备的 bbox 以对齐 y
    other_node_id = equip_to_node.get(other_endpoint, "")
    other_bbox = node_bbox_index.get(other_node_id)
    if other_bbox:
        y_center = (other_bbox[1] + other_bbox[3]) / 2
    else:
        y_center = 0.5

    half = _BN_SIZE / 2
    # 初步计算 y 区间
    y1 = y_center - half
    y2 = y_center + half

    # 防重叠：若与同侧已占用区间冲突，向下偏移直到无冲突
    y1, y2 = _resolve_overlap(y1, y2, occupied, _BN_GAP)

    # 钳制到图纸范围内（保留 margin）
    if y1 < _BN_MARGIN:
        y1 = _BN_MARGIN
        y2 = y1 + _BN_SIZE
    if y2 > 1.0 - _BN_MARGIN:
        y2 = 1.0 - _BN_MARGIN
        y1 = y2 - _BN_SIZE

    # 记录已占用区间
    occupied.append((y1, y2))

    if is_source:
        # 左边缘（留空隙）
        return (_BN_MARGIN, y1, _BN_MARGIN + _BN_SIZE, y2)
    else:
        # 右边缘（留空隙）
        return (1.0 - _BN_MARGIN - _BN_SIZE, y1, 1.0 - _BN_MARGIN, y2)


def _resolve_overlap(
    y1: float,
    y2: float,
    occupied: list[tuple[float, float]],
    gap: float,
) -> tuple[float, float]:
    """若 [y1, y2] 与 occupied 中任一区间重叠，向下偏移直到无冲突。

    采用简单迭代：每次检测冲突就整体下移一个步长，最多迭代 100 次。
    """
    step = (y2 - y1) + gap
    for _ in range(100):
        conflict = False
        for (oy1, oy2) in occupied:
            if y1 < oy2 + gap and oy1 < y2 + gap:
                # 有重叠
                y1 += step
                y2 += step
                conflict = True
                break
        if not conflict:
            return (y1, y2)
    return (y1, y2)
