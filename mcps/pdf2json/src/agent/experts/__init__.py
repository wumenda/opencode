"""
Expert modules for PFD analysis, organized by capability tier.

Plant-level (全厂级):
    - PlantUnitExpert, PlantUnitTopologyExpert, PlantUnitTopologyExpertOneByOne

Unit-level (装置级):
    - EquipmentExpert, BoundaryNodeExpert, DrawingInfoExpert, TableExpert
    - TopologyExpert, PFDTopologyExpert
    - ProcessPackageExpert, ProcessDescriptionTopologyExpert

Equipment-level (设备级):
    - ColumnAssemblyExpert, ReactorAssemblyExpert, EquipmentTypeExpert
"""

from .core.base import BaseExpert, EXPERT_TYPE_MAPPING
from .plant import (
    PlantUnitExpert,
    PlantUnitTopologyExpert,
    PlantUnitTopologyExpertOneByOne,
)
from .unit import (
    EquipmentExpert,
    BoundaryNodeExpert,
    DrawingInfoExpert,
    TableExpert,
    TopologyExpert,
    PFDTopologyExpert,
    ProcessPackageExpert,
    PFDRefluxExpert,
    ProcessDescriptionTopologyExpert,
)
from .equipment import (
    ColumnAssemblyExpert,
    EquipmentTypeExpert,
    ReactorAssemblyExpert,
)

__all__ = [
    "BaseExpert",
    "EXPERT_TYPE_MAPPING",
    "PlantUnitExpert",
    "PlantUnitTopologyExpert",
    "PlantUnitTopologyExpertOneByOne",
    "EquipmentExpert",
    "BoundaryNodeExpert",
    "DrawingInfoExpert",
    "TableExpert",
    "TopologyExpert",
    "PFDTopologyExpert",
    "ProcessPackageExpert",
    "PFDRefluxExpert",
    "ProcessDescriptionTopologyExpert",
    "ColumnAssemblyExpert",
    "EquipmentTypeExpert",
    "ReactorAssemblyExpert",
]
