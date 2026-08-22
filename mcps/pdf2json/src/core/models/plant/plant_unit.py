"""Whole-plant unit topology models.

系统级全厂装置拓扑的图模型：节点（装置/文字目标）+ 边（物料流）。

- ``PlantUnitNode``: 装置节点或文字目标节点（去电厂/调和等）
- ``PlantUnitEdge``: 装置间有向物料流边，携带物料名称与推导方法
- ``PlantUnitDrawing``: 完整拓扑图 = nodes + edges
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator


class PlantUnitFeedInlet(BaseModel):
    """进料口物料描述（纯物料信息，不含拓扑连接）。"""

    model_config = ConfigDict(frozen=False)

    material_name: str
    quantity: Optional[float] = None
    quantity_unit: str = ""
    raw_text: str = ""


class PlantUnitProductOutlet(BaseModel):
    """出料口物料描述（纯物料信息，不含拓扑连接）。"""

    model_config = ConfigDict(frozen=False)

    material_name: str
    share_percent: Optional[float] = None
    quantity: Optional[float] = None
    quantity_unit: str = ""
    raw_text: str = ""


class PlantUnitFeedRequirement(BaseModel):
    """进料组成/性质要求。"""

    model_config = ConfigDict(frozen=False)

    property_name: str
    value: Optional[float] = None
    unit: str = ""
    applies_to: list[str] = Field(default_factory=list)
    raw_text: str = ""


class PlantUnitEdge(BaseModel):
    """装置间有向物料流边。

    两个装置之间可存在多条边（不同物料）。
    ``method`` 记录边的推导来源：``vlm``（VLM 管线提取）或
    ``material_matching``（输入输出物料名精确匹配）。
    """

    model_config = ConfigDict(frozen=False)

    source_node_id: str
    target_node_id: str
    material_name: str
    method: str = ""
    share_percent: Optional[float] = None
    quantity: Optional[float] = None
    quantity_unit: str = ""
    connection_points: list[tuple[float, float]] = Field(default_factory=list)
    raw_text: str = ""


def _dedupe_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


class PlantUnitNode(BaseModel):
    """拓扑图节点：装置节点或文字目标节点。"""

    model_config = ConfigDict(frozen=False)

    id: str
    node_type: str = "plant_unit"
    name: str
    unit_name: str = ""
    unit_trains: list[str] = Field(default_factory=list)
    feeds: list[str] = Field(default_factory=list)
    feed_inlets: list[PlantUnitFeedInlet] = Field(default_factory=list)
    feed_requirements: list[PlantUnitFeedRequirement] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    product_outlets: list[PlantUnitProductOutlet] = Field(default_factory=list)
    position: Optional[tuple[float, float]] = None
    bbox: Optional[tuple[float, float, float, float]] = None
    aliases: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize_unit_names(self) -> "PlantUnitNode":
        if not self.unit_trains:
            metadata_trains = self.metadata.get("sub_units", [])
            if isinstance(metadata_trains, list):
                self.unit_trains = [str(item) for item in metadata_trains if str(item).strip()]

        if not self.unit_name and not self.unit_trains:
            self.unit_name = self.name

        if not self.name:
            self.name = self.display_name

        if not self.feed_inlets and self.feeds:
            self.feed_inlets = [
                PlantUnitFeedInlet(material_name=feed) for feed in _dedupe_nonempty(self.feeds)
            ]
        feed_names = list(self.feeds) + [inlet.material_name for inlet in self.feed_inlets]
        self.feeds = _dedupe_nonempty(feed_names)

        if not self.product_outlets and self.products:
            self.product_outlets = [
                PlantUnitProductOutlet(material_name=product)
                for product in _dedupe_nonempty(self.products)
            ]
        product_names = list(self.products) + [
            outlet.material_name for outlet in self.product_outlets
        ]
        self.products = _dedupe_nonempty(product_names)
        return self

    @property
    def display_name(self) -> str:
        if self.unit_name:
            return self.unit_name
        if self.unit_trains:
            return " / ".join(self.unit_trains)
        return self.name


class PlantUnitDrawing(BaseModel):
    """全厂装置拓扑图 = nodes + edges。"""

    model_config = ConfigDict(frozen=False)

    drawing_id: str
    drawing_name: str = ""
    nodes: list[PlantUnitNode] = Field(default_factory=list)
    edges: list[PlantUnitEdge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _node_map: dict[str, PlantUnitNode] = PrivateAttr(default_factory=dict)

    def get_node(self, node_id: str) -> Optional[PlantUnitNode]:
        if not self._node_map:
            self._node_map = {n.id: n for n in self.nodes}
        return self._node_map.get(node_id)

    def has_node(self, node_id: str) -> bool:
        if not self._node_map:
            self._node_map = {n.id: n for n in self.nodes}
        return node_id in self._node_map

    def get_edges_from(self, node_id: str) -> list[PlantUnitEdge]:
        """获取从指定节点出发的出边。"""
        return [e for e in self.edges if e.source_node_id == node_id]

    def get_edges_to(self, node_id: str) -> list[PlantUnitEdge]:
        """到达指定节点的入边。"""
        return [e for e in self.edges if e.target_node_id == node_id]

    def to_dict(self) -> dict[str, Any]:
        from ..core.serialization import model_to_dict
        return model_to_dict(self)
