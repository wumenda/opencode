"""PFD 工作流 MCP Server —— 将 src/agent/workflow 下的能力封装为 MCP 工具。

使用 FastMCP（HTTP 模式）对外提供以下工具：
    1. pfd_topology        — PFD 图纸拓扑提取 (PFDTopologyWorkflow)
    2. process_package     — 工艺包章节信息提取 (ProcessPackageWorkflow)
    3. plant_unit_topology — 全厂装置拓扑提取 (PlantUnitTopologyWorkflow)
    4. equipment_assembly  — 设备装配图信息提取 (EquipmentAssemblyWorkflow)
"""

from .duck_implement import MCPContent, get_settings
from .server import main, mcp

__all__ = ["MCPContent", "get_settings", "main", "mcp"]
