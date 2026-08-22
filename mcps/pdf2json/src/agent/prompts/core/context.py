from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class PromptContext(BaseModel):
    model_config = ConfigDict(frozen=False)

    process_description: str = ""
    ocr_context_info: str = ""
    ocr_texts: Optional[list[dict[str, Any]]] = None
    equipment_context: Optional[list[dict[str, Any]]] = None
    virtual_node_context: Optional[list[dict[str, Any]]] = None
    arrow_context: Optional[list[dict[str, Any]]] = None
    image_size: Optional[tuple[int, int]] = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def has_process_description(self) -> bool:
        return bool(self.process_description and self.process_description != "未提供工艺流程说明")

    @property
    def has_ocr_context(self) -> bool:
        return bool(self.ocr_context_info and self.ocr_context_info != "未提供OCR上下文。")

    @property
    def has_equipment_context(self) -> bool:
        return bool(self.equipment_context)

    @property
    def has_virtual_node_context(self) -> bool:
        return bool(self.virtual_node_context)

    @property
    def has_arrow_context(self) -> bool:
        return bool(self.arrow_context)

    @property
    def has_image_size(self) -> bool:
        return bool(self.image_size)
