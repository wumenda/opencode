"""LLM-related settings."""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ReasoningEffort(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MINIMAL = "minimal"


class ThinkingType(str, Enum):
    DISABLED = "disabled"
    ENABLED = "enabled"
    ADAPTIVE = "adaptive"
    AUTO = "auto"


class LLMSettings(BaseModel):
    model: str = ""
    base_url: str = ""
    api_key: str = Field(repr=False, default="")
    max_tokens: int = 16092
    max_retries: int = 3
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    seed: Optional[int] = None
    response_format: Optional[dict[str, str]] = None
    timeout: int = 180
    connect_timeout: int = 60
    reasoning_effort: ReasoningEffort = Field(default=ReasoningEffort.NONE)
    thinking_type: ThinkingType = Field(default=ThinkingType.AUTO)
    stream: bool = False
    save_thinking: bool = False
