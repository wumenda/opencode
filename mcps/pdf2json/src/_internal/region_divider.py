from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field


class RegionType(str, Enum):
    MAIN_AREA = "main_area"
    TABLE_AREA = "table_area"
    LEGEND_AREA = "legend_area"
    TITLE_BLOCK = "title_block"
    NOTE_AREA = "note_area"
    UNKNOWN = "unknown"


class Region(BaseModel):
    model_config = ConfigDict(frozen=False)

    region_type: RegionType
    bbox: Tuple[float, float, float, float]
    score: float
    source: str = "rule"
    label: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def x1(self) -> float:
        return self.bbox[0]

    @property
    def y1(self) -> float:
        return self.bbox[1]

    @property
    def x2(self) -> float:
        return self.bbox[2]

    @property
    def y2(self) -> float:
        return self.bbox[3]

    def area_fraction(self, image_width: int, image_height: int) -> float:
        width = max(0.0, self.x2 - self.x1)
        height = max(0.0, self.y2 - self.y1)
        return width * height


class CV2Region(BaseModel):
    model_config = ConfigDict(frozen=False)

    bbox: Tuple[int, int, int, int]
    area: int
    aspect_ratio: float
    has_table_structure: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def x1(self) -> int:
        return self.bbox[0]

    @property
    def y1(self) -> int:
        return self.bbox[1]

    @property
    def x2(self) -> int:
        return self.bbox[2]

    @property
    def y2(self) -> int:
        return self.bbox[3]

    def to_normalized_bbox(self, width: int, height: int) -> Tuple[float, float, float, float]:
        return (
            self.x1 / width,
            self.y1 / height,
            self.x2 / width,
            self.y2 / height,
        )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class RegionDivisionResult(BaseModel):
    model_config = ConfigDict(frozen=False)

    image_width: int
    image_height: int
    regions: List[Region] = Field(default_factory=list)
    unknown_regions: List[Region] = Field(default_factory=list)
    table_bbox: Optional[Tuple[float, float, float, float]] = None
    main_area_bbox: Optional[Tuple[float, float, float, float]] = None
    llm_table_region: Optional[Region] = None
    matched_cv2_region: Optional[CV2Region] = None
    all_cv2_regions: List[CV2Region] = Field(default_factory=list)
    diagnostics: Dict[str, Any] = Field(default_factory=dict)

    @property
    def region_map(self) -> Dict[str, List[Region]]:
        grouped: Dict[str, List[Region]] = {}
        for region in self.regions:
            grouped.setdefault(region.region_type.value, []).append(region)
        return grouped


def _compute_iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = area_a + area_b - inter_area
    return 0.0 if denom <= 0 else inter_area / denom


def _compute_overlap_area(
    box1: Tuple[int, int, int, int],
    box2: Tuple[int, int, int, int],
) -> int:
    ax1, ay1, ax2, ay2 = box1
    bx1, by1, bx2, by2 = box2

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)

    return inter_w * inter_h


def _merge_regions(a: Region, b: Region) -> Region:
    merged_source = a.source if a.source == b.source else "merged"
    return Region(
        region_type=a.region_type,
        bbox=(min(a.x1, b.x1), min(a.y1, b.y1), max(a.x2, b.x2), max(a.y2, b.y2)),
        score=max(a.score, b.score),
        source=merged_source,
        label=a.label or b.label,
        metadata={**b.metadata, **a.metadata},
    )


DEFAULT_TARGET_REGION_TYPES = [
    RegionType.MAIN_AREA.value,
    RegionType.TABLE_AREA.value,
    RegionType.LEGEND_AREA.value,
]


class RegionDivider:
    def __init__(self, settings=None):
        self.settings = settings

    def _normalize_region_type(self, value):
        alias_map = {
            "main": RegionType.MAIN_AREA,
            "main_area": RegionType.MAIN_AREA,
            "drawing_area": RegionType.MAIN_AREA,
            "table": RegionType.TABLE_AREA,
            "table_area": RegionType.TABLE_AREA,
            "legend": RegionType.LEGEND_AREA,
            "legend_area": RegionType.LEGEND_AREA,
            "title_block": RegionType.TITLE_BLOCK,
            "note_area": RegionType.NOTE_AREA,
            "unknown": RegionType.UNKNOWN,
        }
        if not isinstance(value, str):
            return None
        return alias_map.get(value.strip().lower())

    def _normalize_bbox(self, bbox):
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            return None
        try:
            x1, y1, x2, y2 = [float(v) for v in bbox]
        except (TypeError, ValueError):
            return None
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        if left == right or top == bottom:
            return None
        return (left, top, right, bottom)

    def _rule_fallback_regions(self, target_types):
        regions = []
        if RegionType.MAIN_AREA.value in target_types:
            regions.append(
                Region(
                    region_type=RegionType.MAIN_AREA,
                    bbox=(0.05, 0.05, 0.95, 0.95),
                    score=0.3,
                    source="rule",
                    label="rule_fallback_main_area",
                )
            )
        return regions

    def _clip_bbox(self, bbox):
        x1, y1, x2, y2 = bbox
        x1 = min(max(x1, 0.0), 1.0)
        y1 = min(max(y1, 0.0), 1.0)
        x2 = min(max(x2, 0.0), 1.0)
        y2 = min(max(y2, 0.0), 1.0)
        if x1 >= x2 or y1 >= y2:
            return None
        return (x1, y1, x2, y2)

    def _post_process(self, regions, target_types):
        accepted = []
        unknown = []
        for region in regions:
            clipped = self._clip_bbox(region.bbox)
            if clipped is None:
                continue
            region.bbox = clipped
            area = region.area_fraction(1, 1)
            if area < 0.0005:
                continue
            if region.region_type == RegionType.LEGEND_AREA and area > 0.5:
                region.score *= 0.5
            if region.score < 0.2 or region.region_type.value not in target_types:
                unknown.append(
                    Region(
                        region_type=RegionType.UNKNOWN,
                        bbox=region.bbox,
                        score=region.score,
                        source=region.source,
                        label=region.label,
                        metadata={**region.metadata, "original_type": region.region_type.value},
                    )
                )
                continue
            accepted.append(region)

        deduped = []
        for region in accepted:
            merged = False
            for idx, existing in enumerate(deduped):
                if (
                    region.region_type == existing.region_type
                    and _compute_iou(region.bbox, existing.bbox) >= 0.7
                ):
                    deduped[idx] = _merge_regions(existing, region)
                    merged = True
                    break
            if not merged:
                deduped.append(region)
        return deduped, unknown

    def _llm_generate(self, image_path, target_types):
        from src.core.client import VisionAPIClient
        from src.core.infra.config import Settings
        from src.core.io.json_utils import parse_json_safely

        settings = self.settings or Settings.from_env()
        client = VisionAPIClient(settings)

        provider_config, expert_config = settings.get_expert_provider_config("region_division")

        prompt = (
            "Analyze the engineering drawing image and return JSON only with a top-level 'regions' array. "
            "Each item must contain region_type, bbox, score, and label. "
            f"Preferred region types: {', '.join(target_types)}. "
            "bbox must be normalized floats in [0, 1] as [x1, y1, x2, y2]."
        )
        raw_text, _, _ = client.call_api(
            str(image_path),
            prompt,
            provider_config=provider_config,
            expert_config=expert_config,
            max_dimension=expert_config.image_size,
        )
        payload = parse_json_safely(raw_text, expert_type="region_divider")
        if not payload:
            raise ValueError("Failed to parse region JSON")
        regions = []
        for item in payload.get("regions", []):
            region_type = self._normalize_region_type(item.get("region_type"))
            bbox = self._normalize_bbox(item.get("bbox"))
            if region_type is None or bbox is None:
                continue
            regions.append(
                Region(
                    region_type=region_type,
                    bbox=bbox,
                    score=float(item.get("score", 0.5)),
                    source="llm",
                    label=str(item.get("label", "")),
                    metadata={"raw": item},
                )
            )
        return regions

    def _has_table_structure(self, roi: np.ndarray) -> bool:
        if roi.size == 0:
            return False

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
        edges = cv2.Canny(gray, 50, 150)
        lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180, threshold=50, minLineLength=30, maxLineGap=10
        )

        if lines is None:
            return False

        horizontal_lines = 0
        vertical_lines = 0

        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = np.abs(np.arctan2(y2 - y1, x2 - x1))

            if angle < np.pi / 6:
                horizontal_lines += 1
            elif angle > np.pi / 3:
                vertical_lines += 1

        return horizontal_lines >= 2 and vertical_lines >= 2

    def _cv2_detect(
        self,
        image: np.ndarray,
        canny_threshold1: int = 50,
        canny_threshold2: int = 150,
        min_contour_area: int = 1000,
        max_image_width: int = 2000,
    ) -> Tuple[List[CV2Region], Dict[str, Any]]:
        cv2_diagnostics = {"status": "pending", "error": None}

        original_height, original_width = image.shape[:2]

        scale = 1.0
        detection_image = image

        if original_width > max_image_width:
            scale = max_image_width / original_width
            new_width = int(original_width * scale)
            new_height = int(original_height * scale)
            detection_image = cv2.resize(
                image, (new_width, new_height), interpolation=cv2.INTER_NEAREST
            )

        gray = cv2.cvtColor(detection_image, cv2.COLOR_BGR2GRAY)

        white_pixels = np.sum(gray > 250)
        total_pixels = gray.size
        white_ratio = white_pixels / total_pixels

        height, width = detection_image.shape[:2]
        image_area = height * width

        actual_min_contour_area = max(min_contour_area, int(image_area * 0.0001))

        if white_ratio > 0.90:
            canny_threshold1 = max(10, canny_threshold1 // 3)
            canny_threshold2 = max(30, canny_threshold2 // 3)
            actual_min_contour_area = max(500, actual_min_contour_area // 2)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            edges = cv2.Canny(blurred, canny_threshold1, canny_threshold2)
        else:
            edges = cv2.Canny(gray, canny_threshold1, canny_threshold2)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        filtered_contours = [
            cnt for cnt in contours if cv2.contourArea(cnt) > actual_min_contour_area
        ]

        regions = []
        img_height, img_width = detection_image.shape[:2]

        for contour in filtered_contours:
            x, y, w, h = cv2.boundingRect(contour)

            roi = detection_image[y : y + h, x : x + w]
            has_table = self._has_table_structure(roi)

            regions.append(
                CV2Region(
                    bbox=(x, y, x + w, y + h),
                    area=w * h,
                    aspect_ratio=w / h if h > 0 else 0,
                    has_table_structure=has_table,
                )
            )

        regions = sorted(regions, key=lambda r: r.area, reverse=True)

        merged = []
        for region in regions:
            is_overlapping = False
            for merged_region in merged:
                overlap = _compute_overlap_area(region.bbox, merged_region.bbox)
                smaller_area = min(region.area, merged_region.area)
                if smaller_area > 0 and overlap / smaller_area > 0.5:
                    is_overlapping = True
                    break

            if not is_overlapping:
                merged.append(region)

        if scale != 1.0:
            for region in merged:
                x1, y1, x2, y2 = region.bbox
                region.bbox = (
                    int(x1 / scale),
                    int(y1 / scale),
                    int(x2 / scale),
                    int(y2 / scale),
                )
                region.area = int(region.area / (scale * scale))

        cv2_diagnostics["status"] = "success"
        cv2_diagnostics["region_count"] = len(merged)
        cv2_diagnostics["scale"] = scale
        cv2_diagnostics["white_ratio"] = white_ratio

        return merged, cv2_diagnostics

    def _find_table_region(
        self,
        llm_regions: List[Region],
        cv2_regions: List[CV2Region],
        image_width: int,
        image_height: int,
    ) -> Tuple[Optional[Region], Optional[CV2Region], Optional[Tuple[float, float, float, float]]]:
        llm_table_regions = [r for r in llm_regions if r.region_type == RegionType.TABLE_AREA]

        if not llm_table_regions:
            return None, None, None

        llm_table = llm_table_regions[0]
        if len(llm_table_regions) > 1:
            llm_table = max(llm_table_regions, key=lambda r: r.score)

        llm_table_pixel_bbox = (
            int(llm_table.x1 * image_width),
            int(llm_table.y1 * image_height),
            int(llm_table.x2 * image_width),
            int(llm_table.y2 * image_height),
        )

        if not cv2_regions:
            return llm_table, None, llm_table.bbox

        best_cv2_region = None
        max_overlap = 0

        for cv2_region in cv2_regions:
            overlap = _compute_overlap_area(llm_table_pixel_bbox, cv2_region.bbox)
            if overlap > max_overlap:
                max_overlap = overlap
                best_cv2_region = cv2_region

        if best_cv2_region:
            normalized_bbox = best_cv2_region.to_normalized_bbox(image_width, image_height)
            return llm_table, best_cv2_region, normalized_bbox
        else:
            return llm_table, None, llm_table.bbox

    def _compute_main_area(
        self,
        table_bbox: Tuple[float, float, float, float],
    ) -> Tuple[float, float, float, float]:
        table_y1 = table_bbox[1]
        return (0.0, 0.0, 1.0, table_y1)

    def divide(
        self,
        image_input: Union["Image.Image", np.ndarray],
        target_region_types=None,
        use_llm=True,
        use_cv2=True,
        use_parallel=True,
    ):
        if isinstance(image_input, Image.Image):
            image = np.array(image_input)
        else:
            image = image_input
        image_height, image_width = image.shape[:2]
        image_path = None

        target_types = target_region_types or DEFAULT_TARGET_REGION_TYPES
        diagnostics = {
            "image_path": str(image_path) if image_path else "numpy_array",
            "image_size": (image_width, image_height),
            "target_types": list(target_types),
            "use_llm": use_llm,
            "use_cv2": use_cv2,
            "use_parallel": use_parallel,
            "llm_status": "disabled" if not use_llm else "pending",
            "cv2_status": "disabled" if not use_cv2 else "pending",
        }

        llm_regions = []
        cv2_regions = []
        unknown_regions = []
        llm_diagnostics = {}
        cv2_diagnostics = {}

        if use_parallel and use_llm and use_cv2 and image_path:
            with ThreadPoolExecutor(max_workers=2) as executor:
                llm_future = executor.submit(self._llm_generate, image_path, target_types)
                cv2_future = executor.submit(self._cv2_detect, image)

                try:
                    llm_regions = llm_future.result()
                    llm_diagnostics = {"status": "success"}
                    diagnostics["llm_status"] = "success"
                except Exception as exc:
                    llm_regions = []
                    llm_diagnostics = {"status": "error", "error": str(exc)}
                    diagnostics["llm_status"] = f"failed: {exc}"

                try:
                    cv2_regions, cv2_diagnostics = cv2_future.result()
                    diagnostics["cv2_status"] = cv2_diagnostics.get("status", "unknown")
                except Exception as exc:
                    cv2_regions = []
                    cv2_diagnostics = {"status": "error", "error": str(exc)}
                    diagnostics["cv2_status"] = f"failed: {exc}"
        else:
            if use_llm and image_path:
                try:
                    llm_regions = self._llm_generate(image_path, target_types)
                    llm_diagnostics = {"status": "success"}
                    diagnostics["llm_status"] = "success"
                except Exception as exc:
                    llm_diagnostics = {"status": "failed", "error": str(exc)}
                    diagnostics["llm_status"] = f"failed: {exc}"

            if use_cv2:
                try:
                    cv2_regions, cv2_diagnostics = self._cv2_detect(image)
                    diagnostics["cv2_status"] = cv2_diagnostics.get("status", "unknown")
                except Exception as exc:
                    cv2_diagnostics = {"status": "failed", "error": str(exc)}
                    diagnostics["cv2_status"] = f"failed: {exc}"

        diagnostics["llm"] = llm_diagnostics
        diagnostics["cv2"] = cv2_diagnostics

        regions = []
        if llm_regions:
            regions, unknown_regions = self._post_process(llm_regions, target_types)
        else:
            diagnostics["rule_fallback"] = True
            regions = self._rule_fallback_regions(target_types)

        table_bbox = None
        main_area_bbox = None
        llm_table_region = None
        matched_cv2_region = None

        if use_llm and llm_regions and use_cv2 and cv2_regions:
            llm_table_region, matched_cv2_region, table_bbox = self._find_table_region(
                llm_regions, cv2_regions, image_width, image_height
            )
        elif use_llm and llm_regions:
            llm_table_regions = [r for r in llm_regions if r.region_type == RegionType.TABLE_AREA]
            if llm_table_regions:
                llm_table_region = max(llm_table_regions, key=lambda r: r.score)
                table_bbox = llm_table_region.bbox

        if table_bbox:
            main_area_bbox = self._compute_main_area(table_bbox)

        return RegionDivisionResult(
            image_width=image_width,
            image_height=image_height,
            regions=regions,
            unknown_regions=unknown_regions,
            table_bbox=table_bbox,
            main_area_bbox=main_area_bbox,
            llm_table_region=llm_table_region,
            matched_cv2_region=matched_cv2_region,
            all_cv2_regions=cv2_regions,
            diagnostics=diagnostics,
        )


def divide_regions(
    image_input: Union["Image.Image", np.ndarray],
    target_region_types=None,
    use_llm=True,
    use_cv2=True,
    use_parallel=True,
    settings=None,
):
    divider = RegionDivider(settings=settings)
    return divider.divide(
        image_input,
        target_region_types=target_region_types,
        use_llm=use_llm,
        use_cv2=use_cv2,
        use_parallel=use_parallel,
    )
