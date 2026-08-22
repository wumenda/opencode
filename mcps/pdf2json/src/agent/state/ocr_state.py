from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class OCRState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    ocr_output: Optional[dict[str, Any]] = None
    ocr_warnings: list[str] = Field(default_factory=list)
    ocr_match_result: Optional[dict[str, Any]] = None
    ocr_bound_equipment: Optional[dict[str, Any]] = None
    ocr_bound_boundary_nodes: Optional[dict[str, Any]] = None
