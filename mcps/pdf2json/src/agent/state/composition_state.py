from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class CompositionState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    main_area_image_path: Optional[str] = None
    table_area_image_path: Optional[str] = None
    region_division_result: Optional[dict[str, Any]] = None
    table_output: Optional[Any] = None
    composition_match_output: Optional[dict[str, Any]] = None
