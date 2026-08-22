"""
Core models shared across all capability tiers.

Provides:
    - model_to_dict: generic serialization for Pydantic models
    - Validation result containers: ValidationIssue, TopologyValidationResult, ConsistencyIssue, ConsistencyReport
    - Graph check utilities: BFS, adjacency, orphan/duplicate/dangling detection
"""

from .serialization import model_to_dict
from .safe_construct import safe_model_validate
from .validation_results import (
    ConsistencyIssue,
    ConsistencyReport,
    TopologyValidationResult,
    ValidationIssue,
)
from .graph_checks import (
    bfs_reachable,
    build_adjacency_from_edges,
    collect_connected_node_ids,
    find_dangling_edge_refs,
    find_duplicate_edges,
    find_duplicate_stream_numbers,
    find_orphan_node_ids,
    find_self_loop_edges,
    find_unreachable_from_boundary,
)

__all__ = [
    "model_to_dict",
    "safe_model_validate",
    "ConsistencyIssue",
    "ConsistencyReport",
    "TopologyValidationResult",
    "ValidationIssue",
    "bfs_reachable",
    "build_adjacency_from_edges",
    "collect_connected_node_ids",
    "find_dangling_edge_refs",
    "find_duplicate_edges",
    "find_duplicate_stream_numbers",
    "find_orphan_node_ids",
    "find_self_loop_edges",
    "find_unreachable_from_boundary",
]
