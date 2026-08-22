"""
Workflow package - PFD topology extraction workflows, organized by capability tier.

Base:
    - BaseWorkflow: 通用工作流基类

Registry:
    - WorkflowRegistry / list_workflows / get_workflow_info / get_default_registry

Plant-level (全厂级):
    - PlantUnitTopologyWorkflow: VLM 自动判别图纸类型(通用/密集)，再走对应路径提取装置节点与拓扑

Unit-level (装置级):
    - PFDTopologyWorkflow: 设备+边界+DrawingInfo并行 -> 上下文注入拓扑 -> bbox合并
    - ProcessPackageWorkflow: PDF 章节抽取 + 工序说明/反应方程式提取
"""

from .core import (
    BaseWorkflow,
    WorkflowRegistry,
    get_default_registry,
    get_workflow_info,
    list_workflows,
)
from .plant import PlantUnitTopologyWorkflow
from .unit import (
    PFDTopologyWorkflow,
    ProcessPackageWorkflow,
    CompositionTableWorkflow,
    PFDRefluxWorkflow,
)
from .equipment import EquipmentAssemblyWorkflow

__all__ = [
    "BaseWorkflow",
    "WorkflowRegistry",
    "get_default_registry",
    "get_workflow_info",
    "list_workflows",
    "PlantUnitTopologyWorkflow",
    "PFDTopologyWorkflow",
    "ProcessPackageWorkflow",
    "CompositionTableWorkflow",
    "PFDRefluxWorkflow",
    "EquipmentAssemblyWorkflow",
]
