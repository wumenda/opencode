"""
Data models for PFD Topology Extractor v1 - Workflow state models
"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.core.models import PFDDrawing
from src.agent.state import OCRState, ExtractionState, CompositionState, ValidationState


class ImageMetadata(BaseModel):
    """Image metadata including size, format, and other properties."""

    file_path: str
    original_width: int
    original_height: int
    processed_width: int
    processed_height: int
    was_resized: bool
    original_pixels: int
    processed_pixels: int
    format: str = "PNG"
    dpi: Optional[int] = None
    color_mode: str = "RGB"
    bit_depth: int = 24
    file_size_mb: Optional[float] = None


class ExpertOutput(BaseModel):
    """Output from a single expert call."""

    expert_type: str
    success: bool
    data: Any = Field(default_factory=dict)
    image_metadata: Optional[dict[str, Any]] = None
    reasoning_content: Optional[str] = Field(default=None, exclude=True)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TopologyState(BaseModel):

    model_config = ConfigDict(arbitrary_types_allowed=True)

    image_path: str
    image_metadata: Optional[ImageMetadata] = None
    loaded_image: Optional[Any] = Field(default=None, exclude=True)

    pfd_drawing_obj: Optional[PFDDrawing] = None

    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    ocr: OCRState = Field(default_factory=OCRState)
    extraction: ExtractionState = Field(default_factory=ExtractionState)
    composition: CompositionState = Field(default_factory=CompositionState)
    validation: ValidationState = Field(default_factory=ValidationState)
