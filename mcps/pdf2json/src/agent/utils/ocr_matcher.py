"""OCR Matcher - OCR文本与设备/节点的空间匹配绑定"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from src.core import get_logger, Settings

if TYPE_CHECKING:
    from src.core import Settings

logger = get_logger(__name__)

EQUIPMENT_TAG_PATTERN = re.compile(r"^[A-Z]{1,3}-?\d{3,5}[A-Z]?$", re.IGNORECASE)
CROSS_DRAWING_LABEL_PATTERN = re.compile(r"^PFD[-–\s]?\d{3,5}$", re.IGNORECASE)
CROSS_DRAWING_IN_KEYWORDS = ["自", "来自", "from"]
CROSS_DRAWING_DEST_KEYWORDS = ["至", "去往", "to"]


class TextBinding(BaseModel):
    model_config = ConfigDict(frozen=False)

    text_id: str
    text: str
    target_type: str
    target_id: str
    field_name: str
    distance: float
    match_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class OCRMatchResult(BaseModel):
    model_config = ConfigDict(frozen=False)

    equipment_bindings: list[TextBinding] = Field(default_factory=list)
    boundary_node_bindings: list[TextBinding] = Field(default_factory=list)
    unmatched_texts: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    statistics: dict[str, Any] = Field(default_factory=dict)


class OCRMatcher:
    """OCR文本匹配器

    策略概述:
    - 设备节点: 纯最近邻距离匹配，选择bbox中心点最近的OCR文本作为tag
    - 跨图纸节点(cross_drawing_in/out): 多文本聚合匹配，
      一个节点可绑定多个邻近的OCR文本(流股编号+描述文字等)
    - 边界节点(boundary_in/out): BBOX包含+邻近度匹配
    """

    def __init__(
        self,
        equipment_proximity_threshold: float = None,
        cross_drawing_search_radius: float = None,
        cross_drawing_bbox_expansion: float = None,
        boundary_proximity_threshold: float = None,
        settings: Optional["Settings"] = None,
    ):
        _settings = settings or Settings.from_env()
        self.equipment_proximity_threshold = (
            equipment_proximity_threshold
            if equipment_proximity_threshold is not None
            else _settings.ocr_equipment_proximity_threshold
        )
        self.cross_drawing_search_radius = (
            cross_drawing_search_radius
            if cross_drawing_search_radius is not None
            else _settings.ocr_cross_drawing_search_radius
        )
        self.cross_drawing_bbox_expansion = (
            cross_drawing_bbox_expansion
            if cross_drawing_bbox_expansion is not None
            else _settings.ocr_cross_drawing_bbox_expansion
        )
        self.boundary_proximity_threshold = (
            boundary_proximity_threshold
            if boundary_proximity_threshold is not None
            else _settings.ocr_boundary_proximity_threshold
        )

    CROSS_DRAWING_BOUNDARY_TYPES = {"cross_drawing_in", "cross_drawing_out"}
    BOUNDARY_BOUNDARY_TYPES = {"boundary_in", "boundary_out"}
    BINDABLE_BOUNDARY_TYPES = CROSS_DRAWING_BOUNDARY_TYPES | BOUNDARY_BOUNDARY_TYPES

    def match(
        self,
        ocr_output: dict[str, Any],
        equipment_output: Optional[dict[str, Any]],
        boundary_node_output: Optional[dict[str, Any]],
    ) -> OCRMatchResult:
        texts = ocr_output.get("ocr", []) if ocr_output else []
        equipment_list = equipment_output.get("equipment", []) if equipment_output else []
        boundary_nodes = (
            boundary_node_output.get("boundary_node", [])
            if boundary_node_output
            else []
        )

        result = OCRMatchResult()
        used_text_ids: set[str] = set()

        logger.info(
            f"Starting OCR matching: {len(texts)} texts, "
            f"{len(equipment_list)} equipments, {len(boundary_nodes)} boundary_nodes"
        )

        cross_drawings = [
            bn
            for bn in boundary_nodes
            if bn.get("node_type") == "boundary"
            and bn.get("boundary_type") in self.CROSS_DRAWING_BOUNDARY_TYPES
        ]
        for cd_node in cross_drawings:
            bindings = self._match_cross_drawing_multi_text(cd_node, texts, used_text_ids)
            result.boundary_node_bindings.extend(bindings)

        boundaries = [
            bn
            for bn in boundary_nodes
            if bn.get("node_type") == "boundary"
            and bn.get("boundary_type") in self.BOUNDARY_BOUNDARY_TYPES
        ]
        for bn in boundaries:
            bindings = self._match_boundary_node(bn, texts, used_text_ids)
            result.boundary_node_bindings.extend(bindings)

        for equip in equipment_list:
            binding = self._match_equipment_nearest(equip, texts, used_text_ids)
            if binding:
                result.equipment_bindings.append(binding)

        for text_obj in texts:
            text_id = text_obj.get("id", "")
            if text_id and text_id not in used_text_ids:
                result.unmatched_texts.append(text_obj)

        result.statistics = {
            "total_texts": len(texts),
            "matched_texts": len(used_text_ids),
            "equipment_bindings": len(result.equipment_bindings),
            "boundary_node_bindings": len(result.boundary_node_bindings),
            "unmatched_texts": len(result.unmatched_texts),
        }
        logger.info(f"OCR matching completed: {result.statistics}")
        return result

    def _get_node_center(self, node: dict[str, Any]) -> Optional[tuple[float, float]]:
        position = node.get("position")
        if position and len(position) >= 2:
            return (float(position[0]), float(position[1]))
        bbox = node.get("bbox")
        if bbox and len(bbox) >= 4:
            return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
        return None

    @staticmethod
    def _get_text_center(text_obj: dict[str, Any]) -> Optional[tuple[float, float]]:
        center = text_obj.get("center")
        if center and len(center) >= 2:
            return (float(center[0]), float(center[1]))
        bbox = text_obj.get("bbox")
        if bbox and len(bbox) >= 4:
            return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
        return None

    @staticmethod
    def _euclidean_distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
        return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5

    def _expand_bbox(self, bbox: list[float], expansion: float) -> list[float]:
        return [
            max(0.0, bbox[0] - expansion),
            max(0.0, bbox[1] - expansion),
            min(1.0, bbox[2] + expansion),
            min(1.0, bbox[3] + expansion),
        ]

    @staticmethod
    def _point_in_bbox(point: tuple[float, float], bbox: list[float]) -> bool:
        return bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3]

    def _collect_nearby_texts(
        self,
        node_center: tuple[float, float],
        node_bbox: Optional[list[float]],
        texts: list[dict[str, Any]],
        used_text_ids: set[str],
        search_radius: float,
        bbox_expansion: float,
    ) -> list[dict[str, Any]]:
        candidates = []
        expanded_bbox = None
        if node_bbox:
            expanded_bbox = self._expand_bbox(node_bbox, bbox_expansion)

        for text_obj in texts:
            text_id = text_obj.get("id", "")
            if not text_id or text_id in used_text_ids:
                continue
            text_center = self._get_text_center(text_obj)
            if not text_center:
                continue

            distance = self._euclidean_distance(node_center, text_center)
            is_inside_bbox = False
            if expanded_bbox:
                is_inside_bbox = self._point_in_bbox(text_center, expanded_bbox)

            if is_inside_bbox or distance <= search_radius:
                candidates.append(
                    {
                        "text_obj": text_obj,
                        "text_id": text_id,
                        "text": text_obj.get("text", ""),
                        "normalized": text_obj.get(
                            "normalized_text", text_obj.get("text", "")
                        ).upper(),
                        "center": text_center,
                        "distance": distance,
                        "is_bbox_contained": is_inside_bbox,
                    }
                )

        candidates.sort(key=lambda c: (c["distance"]))
        return candidates

    def _classify_cross_drawing_text(self, text: str, normalized: str) -> str:
        if CROSS_DRAWING_LABEL_PATTERN.match(normalized):
            return "drawing_id"
        stripped = text.strip()
        if any(kw in stripped for kw in CROSS_DRAWING_IN_KEYWORDS):
            return "source_desc"
        if any(kw in stripped for kw in CROSS_DRAWING_DEST_KEYWORDS):
            return "dest_desc"
        if EQUIPMENT_TAG_PATTERN.search(normalized):
            return "equipment_ref"
        if re.match(r"^\d{1,4}$", normalized):
            return "stream_number"
        if len(stripped) <= 6 and re.search(r"\d", stripped):
            return "short_label"
        return "description"

    def _match_cross_drawing_multi_text(
        self,
        vnode: dict[str, Any],
        texts: list[dict[str, Any]],
        used_text_ids: set[str],
    ) -> list[TextBinding]:
        vnode_id = vnode.get("id", "")
        boundary_type = vnode.get("boundary_type", "")
        node_center = self._get_node_center(vnode)
        node_bbox = vnode.get("bbox")

        if not node_center:
            return []

        candidates = self._collect_nearby_texts(
            node_center,
            node_bbox,
            texts,
            used_text_ids,
            self.cross_drawing_search_radius,
            self.cross_drawing_bbox_expansion,
        )

        if not candidates:
            logger.debug(f"Cross-drawing node {vnode_id}: no nearby texts found")
            return []

        classified = {}
        for cand in candidates:
            text_class = self._classify_cross_drawing_text(cand["text"], cand["normalized"])
            classified.setdefault(text_class, []).append(cand)

        selected_candidates = []
        priority_order = [
            "drawing_id",
            "source_desc",
            "dest_desc",
            "stream_number",
            "equipment_ref",
            "description",
            "short_label",
        ]
        for cls in priority_order:
            if cls in classified:
                selected_candidates.extend(classified[cls])

        max_bindings = min(len(selected_candidates), 5)
        selected_candidates = selected_candidates[:max_bindings]

        bindings = []
        for idx, cand in enumerate(selected_candidates):
            text_class = self._classify_cross_drawing_text(cand["text"], cand["normalized"])
            distance = cand["distance"]
            is_bbox = cand["is_bbox_contained"]

            field_name = self._determine_field_name(text_class, boundary_type, idx)
            metadata = self._build_metadata(cand, text_class, boundary_type, is_bbox)

            binding = TextBinding(
                text_id=cand["text_id"],
                text=cand["text"],
                target_type="boundary_node",
                target_id=vnode_id,
                field_name=field_name,
                distance=distance,
                match_type="cross_drawing_multi_text",
                metadata=metadata,
            )
            bindings.append(binding)
            used_text_ids.add(cand["text_id"])

        logger.info(
            f"Cross-drawing node {vnode_id} ({boundary_type}): "
            f"bound {len(bindings)} texts - "
            f'{", ".join(f"{b.text}[{b.field_name}]" for b in bindings)}'
        )
        return bindings

    CROSS_DRAWING_FIELD_MAP = {
        "cross_drawing_in": {
            "drawing_id": "drawing_id",
            "stream_number": "description",
            "short_label": "description",
            "source_desc": "description",
            "dest_desc": "description",
            "description": "description",
            "equipment_ref": "equipment_tag",
        },
        "cross_drawing_out": {
            "drawing_id": "drawing_id",
            "stream_number": "description",
            "short_label": "description",
            "source_desc": "description",
            "dest_desc": "description",
            "description": "description",
            "equipment_ref": "equipment_tag",
        },
    }

    CROSS_DRAWING_MODEL_FIELDS = {
        "drawing_id",
        "description",
        "equipment_tag",
    }

    @classmethod
    def _extract_base_field(cls, field_name: str) -> str:
        if field_name in cls.CROSS_DRAWING_MODEL_FIELDS:
            return field_name
        for model_field in cls.CROSS_DRAWING_MODEL_FIELDS:
            if field_name.startswith(model_field + "_"):
                suffix = field_name[len(model_field) + 1 :]
                if suffix.isdigit():
                    return model_field
        return field_name

    @staticmethod
    def _determine_field_name(text_class: str, boundary_type: str, index: int) -> str:
        field_map = OCRMatcher.CROSS_DRAWING_FIELD_MAP.get(boundary_type, {})
        base_field = field_map.get(text_class, text_class)
        if index == 0:
            return base_field
        return f"{base_field}_{index}"

    def _build_metadata(
        self,
        cand: dict[str, Any],
        text_class: str,
        boundary_type: str,
        is_bbox: bool,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "text_class": text_class,
            "boundary_type": boundary_type,
            "match_source": "bbox_containment" if is_bbox else "proximity",
        }
        return meta

    def _match_boundary_node(
        self,
        vnode: dict[str, Any],
        texts: list[dict[str, Any]],
        used_text_ids: set[str],
    ) -> list[TextBinding]:
        vnode_id = vnode.get("id", "")
        boundary_type = vnode.get("boundary_type", "")
        node_center = self._get_node_center(vnode)
        node_bbox = vnode.get("bbox")

        if not node_center:
            return []

        candidates = self._collect_nearby_texts(
            node_center,
            node_bbox,
            texts,
            used_text_ids,
            self.boundary_proximity_threshold,
            self.cross_drawing_bbox_expansion * 0.8,
        )

        if not candidates:
            return []

        best = candidates[0]
        distance = best["distance"]
        is_bbox = best["is_bbox_contained"]

        binding = TextBinding(
            text_id=best["text_id"],
            text=best["text"],
            target_type="boundary_node",
            target_id=vnode_id,
            field_name="equipment_tag",
            distance=distance,
            match_type="boundary_proximity",
            metadata={
                "boundary_type": boundary_type,
                "match_source": "bbox_containment" if is_bbox else "proximity",
            },
        )
        used_text_ids.add(best["text_id"])

        logger.info(f'Boundary node {vnode_id} ({boundary_type}): bound "{best["text"]}"')
        return [binding]

    def _match_equipment_nearest(
        self,
        equip: dict[str, Any],
        texts: list[dict[str, Any]],
        used_text_ids: set[str],
    ) -> Optional[TextBinding]:
        equip_id = equip.get("id", "")
        equip_center = self._get_node_center(equip)

        if not equip_center:
            return None

        best_candidate = None
        best_distance = float("inf")

        for text_obj in texts:
            text_id = text_obj.get("id", "")
            if not text_id or text_id in used_text_ids:
                continue

            text_center = self._get_text_center(text_obj)
            if not text_center:
                continue

            distance = self._euclidean_distance(equip_center, text_center)
            if distance < best_distance:
                best_distance = distance
                best_candidate = text_obj

        if best_candidate is None:
            return None

        if best_distance > self.equipment_proximity_threshold:
            logger.debug(
                f'Equipment {equip_id}: nearest text "{best_candidate.get("text", "")}" '
                f"distance={best_distance:.4f} exceeds threshold {self.equipment_proximity_threshold}"
            )
            return None

        text = best_candidate.get("text", "")
        text_id = best_candidate.get("id", "")

        binding = TextBinding(
            text_id=text_id,
            text=text,
            target_type="equipment",
            target_id=equip_id,
            field_name="tag",
            distance=best_distance,
            match_type="nearest_proximity",
            metadata={
                "match_strategy": "nearest_neighbor",
                "competitor_count": sum(
                    1
                    for t in texts
                    if t.get("id") and t.get("id") not in used_text_ids and self._get_text_center(t)
                ),
            },
        )
        used_text_ids.add(text_id)

        logger.info(f'Equipment {equip_id}: bound tag "{text}" ' f"(distance={best_distance:.4f})")
        return binding

    def apply_bindings(
        self,
        equipment_list: list[dict[str, Any]],
        boundary_nodes: list[dict[str, Any]],
        match_result: OCRMatchResult,
        ocr_texts: Optional[list[dict[str, Any]]] = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        logger.info("Applying OCR bindings to equipment and virtual nodes...")

        equipment_map = {eq.get("id"): eq for eq in equipment_list}
        bnode_map = {bn.get("id"): bn for bn in boundary_nodes}

        for binding in match_result.equipment_bindings:
            equip = equipment_map.get(binding.target_id)
            if not equip:
                continue

            if "ocr_bindings" not in equip:
                equip["ocr_bindings"] = []
            equip["ocr_bindings"].append(
                {
                    "text_id": binding.text_id,
                    "text": binding.text,
                    "field_name": binding.field_name,
                    "match_type": binding.match_type,
                }
            )

            if binding.field_name == "tag":
                if not equip.get("tag"):
                    equip["tag"] = binding.text
                    logger.info(f'set equipment {equip.get("id")} tag to "{binding.text}" from OCR')

        for binding in match_result.boundary_node_bindings:
            vnode = bnode_map.get(binding.target_id)
            if not vnode:
                continue

            if "ocr_bindings" not in vnode:
                vnode["ocr_bindings"] = []
            vnode["ocr_bindings"].append(
                {
                    "text_id": binding.text_id,
                    "text": binding.text,
                    "field_name": binding.field_name,
                    "match_type": binding.match_type,
                }
            )

            if binding.match_type == "boundary_proximity":
                if binding.field_name == "equipment_tag":
                    tags = vnode.get("equipment_tag", [])
                    if isinstance(tags, str):
                        tags = [tags] if tags else []
                    if binding.text not in tags:
                        tags.append(binding.text)
                    vnode["equipment_tag"] = tags
            elif binding.match_type == "cross_drawing_multi_text":
                base_field = self._extract_base_field(binding.field_name)
                if base_field == "equipment_tag":
                    tags = vnode.get("equipment_tag", [])
                    if isinstance(tags, str):
                        tags = [tags] if tags else []
                    if binding.text not in tags:
                        tags.append(binding.text)
                    vnode["equipment_tag"] = tags
                elif base_field not in vnode or not vnode[base_field]:
                    vnode[base_field] = binding.text
                else:
                    vnode[base_field] = vnode[base_field] + " " + binding.text
                logger.info(
                    f'set virtual node {vnode.get("id")} {base_field} '
                    f'to "{vnode[base_field]}" from OCR'
                )
            else:
                vnode[binding.field_name] = binding.text
                logger.info(
                    f'set virtual node {vnode.get("id")} {binding.field_name} '
                    f'to "{binding.text}" from OCR'
                )

        logger.info(
            f"Applied {len(match_result.equipment_bindings)} equipment bindings, "
            f"{len(match_result.boundary_node_bindings)} boundary node bindings"
        )
        return list(equipment_map.values()), list(bnode_map.values())
