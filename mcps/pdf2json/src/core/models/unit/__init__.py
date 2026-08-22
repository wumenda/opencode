"""
Unit-level models (装置级): PFD graph topology for a single drawing.

Core graph types (enums, nodes, edges, drawing) plus control loop,
process knowledge, process package, port validation rules, and
deserialization / builder utilities.
"""

from .enums import (
    NodeType,
    KeypointType,
    BoundaryType,
    PortDirection,
    PortCategory,
    PortOrientation,
    EquipmentType,
    InstrumentType,
    StreamPhase,
    EQUIPMENT_TYPE_ZH_MAP,
    STREAM_PHASE_ZH_MAP,
    KEYPOINT_TYPE_MAP,
)
from .edges import Port, StreamCondition, StreamEdge
from .nodes import (
    PFDNode,
    PFDEquipmentNode,
    InstrumentNode,
    BoundaryNode,
    KeypointNode,
)
from .drawing import DrawingInfo, DrawingValidationResult, PFDDrawing, PFDTopology
from .control_loop import ControlLoopNode
from .process_knowledge import (
    EquipmentRef,
    ConnectionRef,
    FlowSequenceRef,
    ProcessKnowledge,
)
from .process_package import ProcessPackageInfo
from .composition_table import (
    Component,
    CompositionEntry,
    CompositionTable,
    Quantity,
    Stream,
)
from .pfd_reflux import (
    RefluxStructure,
    TowerRefluxDetail,
    TowerOperatingConditions,
    TowerInfo,
    ReactorOperatingConditions,
    ReactorInfo,
    PFDRefluxAnalysis,
)
from .equipment_ports import (
    EquipmentPortConstraint,
    EquipmentPortViolation,
    EquipmentChannelViolation,
    EQUIPMENT_PORT_CONSTRAINTS,
    get_equipment_port_constraint,
    check_equipment_port_count,
    check_equipment_channel,
)
from .keypoint_boundary_ports import (
    SemanticPortRule,
    SEMANTIC_PORT_RULES,
    count_ports_by_direction,
    get_semantic_port_rule,
    has_valid_semantic_ports,
    semantic_port_errors,
)
from .deserialization import DrawingDeserializer, NODE_TYPE_MAP
from .multi_page import (
    DrawingRef,
    CrossPageLink,
    GlobalPFDGraph,
    MultiPageExtractionResult,
    PageGraphBundle,
    UnresolvedCrossDrawingLink,
)
from .model_builder import (
    build_pfd_node,
    build_stream_edge,
    build_pfd_drawing,
    build_pfd_topology,
    pfd_drawing_to_dict,
    pfd_topology_to_dict,
    build_global_pfd_graph,
    global_pfd_graph_to_dict,
)

__all__ = [
    "NodeType",
    "KeypointType",
    "BoundaryType",
    "PortDirection",
    "PortCategory",
    "PortOrientation",
    "EquipmentType",
    "InstrumentType",
    "StreamPhase",
    "EQUIPMENT_TYPE_ZH_MAP",
    "STREAM_PHASE_ZH_MAP",
    "KEYPOINT_TYPE_MAP",
    "Port",
    "StreamCondition",
    "StreamEdge",
    "PFDNode",
    "PFDEquipmentNode",
    "InstrumentNode",
    "BoundaryNode",
    "KeypointNode",
    "DrawingInfo",
    "DrawingValidationResult",
    "PFDDrawing",
    "PFDTopology",
    "ControlLoopNode",
    "EquipmentRef",
    "ConnectionRef",
    "FlowSequenceRef",
    "ProcessKnowledge",
    "ProcessPackageInfo",
    "Component",
    "CompositionEntry",
    "CompositionTable",
    "Quantity",
    "Stream",
    "RefluxStructure",
    "TowerRefluxDetail",
    "TowerOperatingConditions",
    "TowerInfo",
    "ReactorOperatingConditions",
    "ReactorInfo",
    "PFDRefluxAnalysis",
    "EquipmentPortConstraint",
    "EquipmentPortViolation",
    "EquipmentChannelViolation",
    "EQUIPMENT_PORT_CONSTRAINTS",
    "get_equipment_port_constraint",
    "check_equipment_port_count",
    "check_equipment_channel",
    "SemanticPortRule",
    "SEMANTIC_PORT_RULES",
    "count_ports_by_direction",
    "get_semantic_port_rule",
    "has_valid_semantic_ports",
    "semantic_port_errors",
    "DrawingDeserializer",
    "NODE_TYPE_MAP",
    "DrawingRef",
    "CrossPageLink",
    "GlobalPFDGraph",
    "MultiPageExtractionResult",
    "PageGraphBundle",
    "UnresolvedCrossDrawingLink",
    "build_pfd_node",
    "build_stream_edge",
    "build_pfd_drawing",
    "build_pfd_topology",
    "pfd_drawing_to_dict",
    "pfd_topology_to_dict",
    "build_global_pfd_graph",
    "global_pfd_graph_to_dict",
]
