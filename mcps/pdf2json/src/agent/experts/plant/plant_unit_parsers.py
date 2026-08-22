"""Shared parsing helpers for whole-plant unit experts."""

from __future__ import annotations

from typing import Any, cast

from src.core.models import (
    PlantUnitEdge,
    PlantUnitFeedInlet,
    PlantUnitFeedRequirement,
    PlantUnitProductOutlet,
)


def _tuple_or_none(value: Any, expected_len: int) -> tuple[float, ...] | None:
    if not isinstance(value, (list, tuple)) or len(value) != expected_len:
        return None
    try:
        return tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None


def _bbox_from_pixels_or_none(
    value: Any,
    image_size: Any,
) -> tuple[float, float, float, float] | None:
    pixel_bbox = _tuple_or_none(value, 4)
    if pixel_bbox is None:
        return None
    if not isinstance(image_size, (list, tuple)) or len(image_size) != 2:
        return None
    try:
        width = float(image_size[0])
        height = float(image_size[1])
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    x1, y1, x2, y2 = pixel_bbox
    if x2 <= x1 or y2 <= y1:
        return None
    return (
        round(x1 / width, 6),
        round(y1 / height, 6),
        round(x2 / width, 6),
        round(y2 / height, 6),
    )


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_connection_points(value: Any) -> list[tuple[float, float]]:
    if not isinstance(value, list):
        return []

    points: list[tuple[float, float]] = []
    for item in value:
        point = _tuple_or_none(item, 2)
        if point is not None:
            points.append(cast(tuple[float, float], point))
    return points


def _parse_feed_inlets(unit_data: dict[str, Any]) -> list[PlantUnitFeedInlet]:
    feed_data = (
        unit_data.get("feed_inlets")
        or unit_data.get("input_materials")
        or unit_data.get("feeds")
        or []
    )
    if not isinstance(feed_data, list):
        return []

    inlets: list[PlantUnitFeedInlet] = []
    for inlet in feed_data:
        if isinstance(inlet, str):
            material_name = inlet.strip()
            if material_name:
                inlets.append(PlantUnitFeedInlet(material_name=material_name))
            continue
        if not isinstance(inlet, dict):
            continue
        material_name = str(
            inlet.get("material_name") or inlet.get("name") or inlet.get("feed_name") or ""
        ).strip()
        if not material_name:
            continue
        inlets.append(
            PlantUnitFeedInlet(
                material_name=material_name,
                quantity=_float_or_none(inlet.get("quantity")),
                quantity_unit=str(inlet.get("quantity_unit") or ""),
                raw_text=str(inlet.get("raw_text") or ""),
            )
        )
    return inlets


def _parse_feed_requirements(unit_data: dict[str, Any]) -> list[PlantUnitFeedRequirement]:
    requirement_data = (
        unit_data.get("feed_requirements")
        or unit_data.get("input_requirements")
        or unit_data.get("feed_composition_requirements")
        or []
    )
    if not isinstance(requirement_data, list):
        return []

    requirements: list[PlantUnitFeedRequirement] = []
    for requirement in requirement_data:
        if not isinstance(requirement, dict):
            continue
        property_name = str(
            requirement.get("property_name")
            or requirement.get("name")
            or requirement.get("metric_name")
            or ""
        ).strip()
        if not property_name:
            continue
        requirements.append(
            PlantUnitFeedRequirement(
                property_name=property_name,
                value=_float_or_none(requirement.get("value")),
                unit=str(requirement.get("unit") or ""),
                applies_to=[
                    str(material)
                    for material in requirement.get("applies_to", [])
                    if str(material).strip()
                ],
                raw_text=str(requirement.get("raw_text") or ""),
            )
        )
    return requirements


def _parse_product_outlets(
    unit_data: dict[str, Any],
    field_name: str = "product_outlets",
) -> list[PlantUnitProductOutlet]:
    outlet_data = (
        unit_data.get(field_name)
        or unit_data.get("product_materials")
        or unit_data.get("output_materials")
        or unit_data.get("products")
        or []
    )
    if not isinstance(outlet_data, list):
        return []

    outlets: list[PlantUnitProductOutlet] = []
    for outlet in outlet_data:
        if isinstance(outlet, str):
            material_name = outlet.strip()
            if material_name:
                outlets.append(PlantUnitProductOutlet(material_name=material_name))
            continue
        if not isinstance(outlet, dict):
            continue
        material_name = str(
            outlet.get("material_name") or outlet.get("name") or outlet.get("product_name") or ""
        ).strip()
        if not material_name:
            continue
        outlets.append(
            PlantUnitProductOutlet(
                material_name=material_name,
                share_percent=_float_or_none(
                    outlet.get("share_percent")
                    if "share_percent" in outlet
                    else outlet.get("percentage")
                ),
                quantity=_float_or_none(outlet.get("quantity")),
                quantity_unit=str(outlet.get("quantity_unit") or ""),
                raw_text=str(outlet.get("raw_text") or ""),
            )
        )
    return outlets


def _parse_edges_from_outlets(
    source_unit_id: str,
    outlet_data: Any,
    method: str = "vlm",
) -> list[PlantUnitEdge]:
    """将 VLM 返回的 outlet 数据（含 target 列表）展开为有向边列表。

    每个 outlet 的 ``target`` 中的每个目标装置生成一条独立的 ``PlantUnitEdge``。
    """
    if not isinstance(outlet_data, list):
        return []

    edges: list[PlantUnitEdge] = []
    for outlet in outlet_data:
        if isinstance(outlet, str):
            continue
        if not isinstance(outlet, dict):
            continue
        material_name = str(
            outlet.get("material_name") or outlet.get("name") or outlet.get("product_name") or ""
        ).strip()
        if not material_name:
            continue
        targets = [str(t).strip() for t in outlet.get("target", []) if str(t).strip()]
        if not targets:
            continue
        share_percent = _float_or_none(
            outlet.get("share_percent")
            if "share_percent" in outlet
            else outlet.get("percentage")
        )
        quantity = _float_or_none(outlet.get("quantity"))
        quantity_unit = str(outlet.get("quantity_unit", ""))
        connection_points = _parse_connection_points(
            outlet.get("connection_points") or outlet.get("outlet_points") or []
        )
        raw_text = str(outlet.get("raw_text", ""))
        for target_id in targets:
            edges.append(
                PlantUnitEdge(
                    source_node_id=source_unit_id,
                    target_node_id=target_id,
                    material_name=material_name,
                    method=method,
                    share_percent=share_percent,
                    quantity=quantity,
                    quantity_unit=quantity_unit,
                    connection_points=connection_points,
                    raw_text=raw_text,
                )
            )
    return edges
