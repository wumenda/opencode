"""Image processing settings."""
from pydantic import BaseModel, Field


DEFAULT_EXPERT_IMAGE_SIZES: dict[str, int] = {
    "arrow": 4096,
    "equipment": 2048,
    "valve": 2048,
    "stream_edge": 4096,
    "boundary_node": 3072,
    "virtual_node": 3072,
    "cross_drawing_boundary": 4096,
    "ocr": 4096,
    "region_division": 4096,
    "drawing_region": 4096,
    "topology": 4096,
    "topology_correction": 4096,
    "pipeline_keypoint": 2048,
    "arrow_detection": 2048,
    "port_detection": 2048,
    "reactor_assembly": 4096,
    "column_assembly": 4096,
}


class ImageSettings(BaseModel):
    max_image_size: int = 4096
    max_image_pixels: int = 36_000_000
    expert_image_sizes: dict[str, int] = Field(
        default_factory=DEFAULT_EXPERT_IMAGE_SIZES.copy
    )
    keep_temp_files: bool = False
