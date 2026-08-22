from __future__ import annotations

import logging
from typing import Any, Optional

from src.core.models import (
    BoundaryType,
    Port,
    PortCategory,
    PortDirection,
)

logger = logging.getLogger(__name__)

_BOUNDARY_TYPE_EXPECTED_PORTS: dict[BoundaryType, tuple[PortDirection, ...]] = {
    BoundaryType.BOUNDARY_IN: (PortDirection.OUTPUT,),
    BoundaryType.BOUNDARY_OUT: (PortDirection.INPUT,),
    BoundaryType.CROSS_DRAWING_IN: (PortDirection.INPUT, PortDirection.OUTPUT),
    BoundaryType.CROSS_DRAWING_OUT: (PortDirection.INPUT, PortDirection.OUTPUT),
}


def _extract_vlm_position(
    vlm_ports_data: list[dict[str, Any]], index: int
) -> Optional[tuple[float, float]]:
    if index < len(vlm_ports_data):
        pos = vlm_ports_data[index].get("position")
        if pos:
            return tuple(pos)
    return None


def _auto_generate_port(
    node_id: str,
    direction: PortDirection,
    position: Optional[tuple[float, float]] = None,
) -> Port:
    return Port(
        id=f"{node_id}_{direction.value}_1",
        direction=direction,
        category=PortCategory.PROCESS,
        position=position,
        parent_node_id=node_id,
    )


def _fix_port_id_direction(port_id: str, target_direction: PortDirection) -> str:
    if target_direction == PortDirection.INPUT:
        return port_id.replace("_out_", "_in_").replace("_unknown_", "_in_")
    if target_direction == PortDirection.OUTPUT:
        return port_id.replace("_in_", "_out_").replace("_unknown_", "_out_")
    return port_id


def ensure_correct_boundary_ports(
    node_id: str,
    parsed_ports: list[Port],
    boundary_type: Optional[BoundaryType],
    vlm_ports_data: list[dict[str, Any]],
) -> list[Port]:
    expected_directions = (
        _BOUNDARY_TYPE_EXPECTED_PORTS.get(boundary_type) if boundary_type else None
    )
    if expected_directions is None:
        return parsed_ports

    if len(expected_directions) == 1:
        return _ensure_single_direction_ports(
            node_id, parsed_ports, expected_directions[0], vlm_ports_data
        )

    return _ensure_dual_direction_ports(node_id, parsed_ports, expected_directions, vlm_ports_data)


def _ensure_single_direction_ports(
    node_id: str,
    parsed_ports: list[Port],
    expected_direction: PortDirection,
    vlm_ports_data: list[dict[str, Any]],
) -> list[Port]:
    if not parsed_ports:
        logger.debug(
            "Node %s: VLM returned no ports, auto-generating %s port for %s",
            node_id,
            expected_direction.value,
            expected_direction.value,
        )
        position = _extract_vlm_position(vlm_ports_data, 0)
        return [_auto_generate_port(node_id, expected_direction, position)]

    corrected = []
    for port in parsed_ports:
        if port.direction != expected_direction:
            logger.debug(
                "Node %s: correcting port %s direction from %s to %s",
                node_id,
                port.id,
                port.direction.value,
                expected_direction.value,
            )
            new_id = _fix_port_id_direction(port.id, expected_direction)
            corrected.append(
                port.model_copy(update={"direction": expected_direction, "id": new_id})
            )
        else:
            corrected.append(port)

    return corrected


def _ensure_dual_direction_ports(
    node_id: str,
    parsed_ports: list[Port],
    expected_directions: tuple[PortDirection, ...],
    vlm_ports_data: list[dict[str, Any]],
) -> list[Port]:
    used_indices: set[int] = set()
    result: list[Port] = []

    for dir_idx, target_direction in enumerate(expected_directions):
        port = _find_or_create_port_for_direction(
            node_id,
            parsed_ports,
            target_direction,
            used_indices,
            vlm_ports_data,
            dir_idx,
        )
        result.append(port)

    return result


def _find_or_create_port_for_direction(
    node_id: str,
    parsed_ports: list[Port],
    target_direction: PortDirection,
    used_indices: set[int],
    vlm_ports_data: list[dict[str, Any]],
    vlm_index: int,
) -> Port:
    for i, port in enumerate(parsed_ports):
        if i in used_indices:
            continue
        if port.direction == target_direction:
            used_indices.add(i)
            return port

    for i, port in enumerate(parsed_ports):
        if i in used_indices:
            continue
        if port.direction == PortDirection.UNKNOWN:
            used_indices.add(i)
            new_id = _fix_port_id_direction(port.id, target_direction)
            logger.debug(
                "Node %s: converting UNKNOWN port %s to %s",
                node_id,
                port.id,
                target_direction.value,
            )
            return port.model_copy(update={"direction": target_direction, "id": new_id})

    for i, port in enumerate(parsed_ports):
        if i in used_indices:
            continue
        used_indices.add(i)
        new_id = _fix_port_id_direction(port.id, target_direction)
        logger.debug(
            "Node %s: converting port %s direction from %s to %s",
            node_id,
            port.id,
            port.direction.value,
            target_direction.value,
        )
        return port.model_copy(update={"direction": target_direction, "id": new_id})

    logger.debug(
        "Node %s: auto-generating %s port (no suitable port found in VLM output)",
        node_id,
        target_direction.value,
    )
    position = _extract_vlm_position(vlm_ports_data, vlm_index)
    return _auto_generate_port(node_id, target_direction, position)
