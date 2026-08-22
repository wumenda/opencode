"""Equipment / Boundary / TopologyEdge extraction evaluation module.

Provides algorithms to compare extraction results against ground-truth labels.
"""

from .metrics import MetricSet
from .equipment_evaluator import (
    EquipmentEvaluator,
    EquipmentEvaluationReport,
    EquipmentDiff,
    PortPairDiff,
    evaluate_equipment_sample,
)
from .boundary_evaluator import (
    BoundaryEvaluator,
    BoundaryEvaluationReport,
    BoundaryDiff,
    evaluate_boundary_sample,
)
from .topology_edge_evaluator import (
    TopologyEdgeEvaluator,
    TopologyEdgeReport,
    EdgeMatchDetail,
    evaluate_topology_edge_sample,
)

__all__ = [
    # shared metrics
    "MetricSet",
    # equipment
    "EquipmentEvaluator",
    "EquipmentEvaluationReport",
    "EquipmentDiff",
    "PortPairDiff",
    "evaluate_equipment_sample",
    # boundary
    "BoundaryEvaluator",
    "BoundaryEvaluationReport",
    "BoundaryDiff",
    "evaluate_boundary_sample",
    # topology edge
    "TopologyEdgeEvaluator",
    "TopologyEdgeReport",
    "EdgeMatchDetail",
    "evaluate_topology_edge_sample",
]
