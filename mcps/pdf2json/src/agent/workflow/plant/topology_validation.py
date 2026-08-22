"""Shared topology post-processing helpers for plant-unit workflows.

提供以下能力，供合并后的 PlantUnitTopologyWorkflow 复用：

- ``validate_edges_against_feeds``: 校验 VLM 提取的边——若 target 装置的 feeds
  中不包含该物料名，则移除该边（VLM 幻觉修复）。
- ``fallback_material_matching``: 为 VLM 未提取到任何出边的装置，用物料名匹配
  算法回补缺失的边。
- ``infer_topology_by_material_matching``: dense 路径的核心算法——根据装置
  feeds/products 物料名做精确匹配，推理装置间有向物料流边（含多生产源过滤）。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _material_key(material: str) -> str:
    return str(material or "").strip().casefold()


def _collect_feed_names(unit: dict[str, Any]) -> set[str]:
    """收集装置的全部进料物料名（plain feeds + feed_inlets），返回 casefold 集合。"""
    names: set[str] = set()
    for feed in unit.get("feeds", []) or []:
        text = str(feed).strip()
        if text:
            names.add(_material_key(text))
    for inlet in unit.get("feed_inlets", []) or []:
        if isinstance(inlet, dict):
            text = str(inlet.get("material_name", "")).strip()
            if text:
                names.add(_material_key(text))
        elif isinstance(inlet, str) and inlet.strip():
            names.add(_material_key(inlet))
    return names


def _collect_product_names(unit: dict[str, Any]) -> list[str]:
    """收集装置的全部产物物料名（products + product_outlets），去重保序。"""
    names: list[str] = []
    seen: set[str] = set()

    def _add(name: Any) -> None:
        text = str(name or "").strip()
        if not text:
            return
        key = _material_key(text)
        if key in seen:
            return
        seen.add(key)
        names.append(text)

    for product in unit.get("products", []) or []:
        _add(product)
    for outlet in unit.get("product_outlets", []) or []:
        if isinstance(outlet, dict):
            _add(outlet.get("material_name"))
        elif isinstance(outlet, str):
            _add(outlet)
    return names


def validate_edges_against_feeds(
    edges: list[dict[str, Any]],
    plant_units: list[dict[str, Any]],
    text_destinations: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """校验 VLM 提取的边：若 target 装置 feeds 中不含该物料，移除该边。

    返回 (filtered_edges, warnings)。
    text_destination 节点不校验（它们没有 feeds 列表，只接收物料）。
    """
    # 构建 unit_id → feed 物料名集合 的索引
    feed_index: dict[str, set[str]] = {}
    all_node_ids: set[str] = set()
    for unit in plant_units:
        unit_id = str(unit.get("id", "")).strip()
        if unit_id:
            feed_index[unit_id] = _collect_feed_names(unit)
            all_node_ids.add(unit_id)

    # text_destination 节点加入 all_node_ids（不校验 feeds）
    for dest in text_destinations or []:
        dest_id = str(dest.get("id", "")).strip()
        if dest_id:
            all_node_ids.add(dest_id)

    filtered: list[dict[str, Any]] = []
    removed: list[str] = []
    for edge in edges:
        target_id = str(edge.get("target_node_id", "")).strip()
        material = str(edge.get("material_name", "")).strip()
        # target 不在已知节点列表中 → 保留（可能是图外去向，交由上层处理）
        if target_id not in all_node_ids:
            filtered.append(edge)
            continue
        # target 是 text_destination → 保留
        if target_id not in feed_index:
            filtered.append(edge)
            continue
        # target 是装置 → 检查 feeds 中是否含该物料
        feed_names = feed_index[target_id]
        if _material_key(material) in feed_names:
            filtered.append(edge)
        else:
            source_id = str(edge.get("source_node_id", ""))
            removed.append(
                f"移除无效边: {source_id} -> {target_id} [{material}]"
                f"（{target_id} 的 feeds 中不包含 '{material}'）"
            )

    return filtered, removed


def fallback_material_matching(
    edges: list[dict[str, Any]],
    plant_units: list[dict[str, Any]],
    text_destinations: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """为 0 出边的装置用物料名匹配回补缺失的边。

    仅对 VLM 提取的边（method == 'vlm'）生效。
    返回 (edges_with_fallback, warnings)。
    """
    # 收集已有出边的 source 节点
    sources_with_edges: set[str] = set()
    for edge in edges:
        if edge.get("method", "") == "vlm":
            sources_with_edges.add(str(edge.get("source_node_id", "")).strip())

    # 收集每个物料的 consumers（仅装置节点的 feeds）
    consumers: dict[str, list[str]] = defaultdict(list)
    for unit in plant_units:
        unit_id = str(unit.get("id", "")).strip()
        if not unit_id:
            continue
        for feed_name in _collect_feed_names(unit):
            consumers[feed_name].append(unit_id)

    # text_destination 节点不作为 consumer 回补目标

    fallback_edges: list[dict[str, Any]] = []
    warnings: list[str] = []
    for unit in plant_units:
        unit_id = str(unit.get("id", "")).strip()
        if not unit_id or unit_id in sources_with_edges:
            continue
        products = _collect_product_names(unit)
        if not products:
            continue
        unit_name = unit.get("name") or unit.get("unit_name") or unit_id
        unit_edge_count = 0
        for product in products:
            key = _material_key(product)
            for target_id in consumers.get(key, []):
                if target_id == unit_id:
                    continue
                fallback_edges.append({
                    "source_node_id": unit_id,
                    "target_node_id": target_id,
                    "material_name": product,
                    "method": "material_matching_fallback",
                })
                unit_edge_count += 1
        if unit_edge_count > 0:
            warnings.append(
                f"装置 '{unit_name}' ({unit_id}) VLM 未提取到出边，"
                f"已用物料名匹配回补 {unit_edge_count} 条边"
            )

    return edges + fallback_edges, warnings


# ----------------------------------------------------------------------
# Dense 路径：物料名匹配算法（无 VLM）
# ----------------------------------------------------------------------

def _float_or_zero(value: Any) -> float:
    """安全转换为 float，失败返回 0.0。"""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _collect_material_names(plain: Any, structured: Any) -> list[str]:
    """合并 plain materials 与 structured inlets/outlets 中的 material_name，去重保序。"""
    names: list[str] = []
    seen: set[str] = set()

    def _add(name: Any) -> None:
        text = str(name or "").strip()
        if not text:
            return
        key = _material_key(text)
        if key in seen:
            return
        seen.add(key)
        names.append(text)

    if isinstance(plain, list):
        for item in plain:
            _add(item)
    if isinstance(structured, list):
        for entry in structured:
            if isinstance(entry, dict):
                _add(entry.get("material_name"))
            else:
                _add(entry)
    return names


def _collect_consumer_material_names(
    plain: Any, structured: Any
) -> list[str]:
    """收集进料物料名，跳过 quantity==0 的 feed_inlet（零流量进料不生成边）。"""
    names: list[str] = []
    seen: set[str] = set()

    def _add(name: Any) -> None:
        text = str(name or "").strip()
        if not text:
            return
        key = _material_key(text)
        if key in seen:
            return
        seen.add(key)
        names.append(text)

    if isinstance(structured, list):
        for entry in structured:
            if isinstance(entry, dict):
                quantity = entry.get("quantity")
                if quantity is not None and isinstance(quantity, (int, float)) and float(quantity) == 0:
                    continue
                _add(entry.get("material_name"))
            else:
                _add(entry)
    elif isinstance(plain, list):
        for item in plain:
            _add(item)
    return names


def infer_topology_by_material_matching(
    plant_units: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """根据装置 feeds/products 物料名做精确匹配，推理装置间有向物料流边。

    构图规则：若装置 A 的 products 与装置 B 的 feeds 存在同名物料，
    则生成 A → B 的边。多生产源过滤：当物料有多个生产者时，仅保留产量最大的生产者。
    """
    if not plant_units:
        return []

    consumers: dict[str, list[str]] = defaultdict(list)
    unit_products: dict[str, list[str]] = {}
    producers: dict[str, list[tuple[str, float]]] = defaultdict(list)

    for unit in plant_units:
        unit_id = str(unit.get("id", "")).strip()
        if not unit_id:
            continue
        products = _collect_material_names(
            unit.get("products"), unit.get("product_outlets")
        )
        feeds = _collect_consumer_material_names(
            unit.get("feeds"), unit.get("feed_inlets")
        )
        unit_products[unit_id] = products
        for material in feeds:
            consumers[_material_key(material)].append(unit_id)
        for outlet in unit.get("product_outlets", []) or []:
            if isinstance(outlet, dict):
                mat = str(outlet.get("material_name", "")).strip()
                if mat:
                    qty = _float_or_zero(outlet.get("quantity"))
                    producers[_material_key(mat)].append((unit_id, qty))

    edges: list[dict[str, Any]] = []
    for unit in plant_units:
        unit_id = str(unit.get("id", "")).strip()
        if not unit_id:
            continue
        for material in unit_products.get(unit_id, []):
            key = _material_key(material)
            target_ids = sorted(
                {cid for cid in consumers.get(key, []) if cid != unit_id}
            )
            if not target_ids:
                continue
            producer_list = producers.get(key, [])
            if len(producer_list) > 1:
                max_producer = max(producer_list, key=lambda x: x[1])
                if unit_id != max_producer[0]:
                    continue
            for target_id in target_ids:
                edges.append({
                    "source_node_id": unit_id,
                    "target_node_id": target_id,
                    "material_name": material,
                    "method": "material_matching",
                })

    return edges

