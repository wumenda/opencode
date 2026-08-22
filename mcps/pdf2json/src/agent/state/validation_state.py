from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from src.core.models import PFDDrawing
from src.core.models.core.validation_results import (
    ConsistencyReport,
    TopologyValidationResult,
)


class ValidationState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    final_drawing: Optional[PFDDrawing] = None
    consistency_result: Optional[ConsistencyReport] = None
    validation_result: Optional[TopologyValidationResult] = None
    gated_drawing: Optional[PFDDrawing] = None
    evidence_report: Optional[dict[str, Any]] = None
    process_description_validation_report: Optional[dict[str, Any]] = None
    refinement_output: Optional[Any] = None
    correction_output: Optional[dict[str, Any]] = None
    global_structure_output: Optional[dict[str, Any]] = None
