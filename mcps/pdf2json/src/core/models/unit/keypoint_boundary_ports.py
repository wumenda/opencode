"""Port direction rules for boundary nodes and keypoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .enums import BoundaryType, NodeType, PortDirection


@dataclass(frozen=True)
class SemanticPortRule:
    required_directions: tuple[PortDirection, ...]
    forbidden_directions: tuple[PortDirection, ...]
    class_name: str
    description_zh: str


SEMANTIC_PORT_RULES: dict[BoundaryType, SemanticPortRule] = {
    BoundaryType.BOUNDARY_IN: SemanticPortRule(
        required_directions=(PortDirection.OUTPUT,),
        forbidden_directions=(PortDirection.INPUT,),
        class_name="BoundaryNode",
        description_zh="界区进料节点",
    ),
    BoundaryType.BOUNDARY_OUT: SemanticPortRule(
        required_directions=(PortDirection.INPUT,),
        forbidden_directions=(PortDirection.OUTPUT,),
        class_name="BoundaryNode",
        description_zh="界区出料节点",
    ),
    BoundaryType.CROSS_DRAWING_IN: SemanticPortRule(
        required_directions=(PortDirection.INPUT, PortDirection.OUTPUT),
        forbidden_directions=(),
        class_name="BoundaryNode",
        description_zh="跨图纸来节点",
    ),
    BoundaryType.CROSS_DRAWING_OUT: SemanticPortRule(
        required_directions=(PortDirection.INPUT, PortDirection.OUTPUT),
        forbidden_directions=(),
        class_name="BoundaryNode",
        description_zh="跨图纸去节点",
    ),
}


def get_semantic_port_rule(key: BoundaryType | NodeType | str) -> SemanticPortRule | None:
    if isinstance(key, BoundaryType):
        return SEMANTIC_PORT_RULES.get(key)
    try:
        boundary_type = BoundaryType(key)
        return SEMANTIC_PORT_RULES.get(boundary_type)
    except ValueError:
        pass
    try:
        node_type = NodeType(key)
        if node_type == NodeType.BOUNDARY:
            return None
    except ValueError:
        pass
    return None


def count_ports_by_direction(node: Any) -> tuple[int, int]:
    input_count = len(node.get_input_ports()) if hasattr(node, "get_input_ports") else 0
    output_count = len(node.get_output_ports()) if hasattr(node, "get_output_ports") else 0
    return input_count, output_count


def semantic_port_errors(node: Any) -> list[str]:
    from .nodes import BoundaryNode

    if isinstance(node, BoundaryNode):
        rule = get_semantic_port_rule(node.boundary_type)
    else:
        rule = get_semantic_port_rule(getattr(node, "node_type", ""))
    if rule is None:
        return []

    input_count, output_count = count_ports_by_direction(node)
    counts = {
        PortDirection.INPUT: input_count,
        PortDirection.OUTPUT: output_count,
    }
    errors: list[str] = []

    for direction in rule.required_directions:
        if counts[direction] < 1:
            errors.append(
                f"{rule.class_name} '{node.id}' must have at least one " f"{direction.value} port"
            )
    for direction in rule.forbidden_directions:
        if counts[direction] > 0:
            errors.append(f"{rule.class_name} '{node.id}' must have no {direction.value} ports")

    return errors


def has_valid_semantic_ports(node: Any) -> bool:
    return not semantic_port_errors(node)
