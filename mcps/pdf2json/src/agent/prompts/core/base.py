from abc import ABC, abstractmethod
from typing import Any, Optional

from .context import PromptContext


class PromptBuilder(ABC):
    expert_type: str = ""
    version: str = ""

    @abstractmethod
    def build(self, context: PromptContext) -> str: ...

    @abstractmethod
    def get_output_schema(self) -> dict[str, Any]: ...

    def build_image_size_section(self, image_size: Optional[tuple[int, int]]) -> str:
        if image_size is None:
            return ""
        return (
            "\n        【输入图片尺寸信息】\n"
            f"        输入图片的像素尺寸为: {image_size[0]} × {image_size[1]} (宽 × 高)\n"
            "        所有坐标均为归一化坐标(0.0-1.0)，与图片尺寸无关；图片尺寸仅供你参考，帮助判断图中元素的相对大小和间距。所有坐标值必须使用小数（如0.5），禁止使用分数（如1/2）。\n"
        )

    def build_process_description_section(self, process_description: str) -> str:
        if not process_description or process_description == "未提供工艺流程说明":
            return ""
        return (
            "\n        【工艺流程说明 - 辅助背景】\n"
            "        以下是整个装置的工艺流程说明，当前分析的图纸只是该装置流程的一部分：\n\n"
            f"        {process_description}\n\n"
            "        【使用原则】\n"
            "        - 工艺流程说明仅作为辅助背景，用于帮助理解设备功能、物流去向和名称\n"
            "        - 如果流程说明与图上可见信息冲突，以图上可见信息为准\n"
            "        - 不要因为流程说明里提到了某个设备或流股，就在图上补出不存在的对象\n"
        )
