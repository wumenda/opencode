from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WorkflowInfo(BaseModel):
    name: str
    module_path: str
    class_name: str
    extra_kwargs: dict[str, Any] = Field(default_factory=dict)


_WORKFLOW_DEFINITIONS: list[dict[str, str | bool | dict[str, bool]]] = [
    {
        "name": "pfd_topology",
        "module_path": "src.agent.workflow.unit.pfd_topology",
        "class_name": "PFDTopologyWorkflow",
    },
    {
        "name": "process_package",
        "module_path": "src.agent.workflow.unit.process_package",
        "class_name": "ProcessPackageWorkflow",
    },
    {
        "name": "composition_table",
        "module_path": "src.agent.workflow.unit.composition_table",
        "class_name": "CompositionTableWorkflow",
    },
    {
        "name": "pfd_reflux",
        "module_path": "src.agent.workflow.unit.pfd_reflux",
        "class_name": "PFDRefluxWorkflow",
    },
    {
        "name": "equipment_assembly",
        "module_path": "src.agent.workflow.equipment.equipment_assembly",
        "class_name": "EquipmentAssemblyWorkflow",
    },
]

WORKFLOW_DISPLAY_META: dict[str, dict[str, str]] = {
    "pfd_topology": {
        "name": "上下文拓扑提取",
        "description": "设备+边界节点并行提取位置，注入topology上下文，合并bbox",
        "category": "one_shot",
        "badge": "TC",
    },
    "process_package": {
        "name": "工艺包章节信息提取",
        "description": "按章节序号/标题定位 PDF 章节，提取工序说明与反应方程式",
        "category": "one_shot",
        "badge": "PP",
    },
    "composition_table": {
        "name": "组分表信息提取",
        "description": "PDF 逐页转图，提取组分表（组分定义 + 物流组成）并聚合输出",
        "category": "one_shot",
        "badge": "CT",
    },
    "pfd_reflux": {
        "name": "PFD塔回流结构分析",
        "description": "识别PFD中所有塔与反应器，判断回流结构，提取冷凝器/再沸器/回流量与操作条件",
        "category": "one_shot",
        "badge": "PR",
    },
    "plant_unit_topology": {
        "name": "整厂装置拓扑提取",
        "description": "VLM 自动判别图纸类型(通用/密集)，再走对应路径提取装置节点与拓扑",
        "category": "one_shot",
        "badge": "PU",
    },
    "equipment_assembly": {
        "name": "设备装配图信息提取",
        "description": "VLM 自动判别设备类型（板式塔/填料塔/反应器），再路由到对应专家提取装配信息",
        "category": "one_shot",
        "badge": "EA",
    },
}


class WorkflowRegistry:
    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowInfo] = {}

    def register(self, info: WorkflowInfo) -> None:
        self._workflows[info.name] = info

    def get(self, name: str) -> WorkflowInfo | None:
        return self._workflows.get(name)

    def list_names(self) -> list[str]:
        return sorted(self._workflows.keys())

    def auto_discover(self) -> None:
        for defn in _WORKFLOW_DEFINITIONS:
            extra_kwargs: dict[str, bool] = {}
            if defn.get("enable_ocr_binding"):
                extra_kwargs["enable_ocr_binding"] = True
            info = WorkflowInfo(
                name=str(defn["name"]),
                module_path=str(defn["module_path"]),
                class_name=str(defn["class_name"]),
                extra_kwargs=extra_kwargs,
            )
            self.register(info)


_default_registry: WorkflowRegistry | None = None


def get_default_registry() -> WorkflowRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = WorkflowRegistry()
        _default_registry.auto_discover()
    return _default_registry


def list_workflows() -> list[str]:
    return get_default_registry().list_names()


def get_workflow_info(name: str) -> WorkflowInfo | None:
    return get_default_registry().get(name)
