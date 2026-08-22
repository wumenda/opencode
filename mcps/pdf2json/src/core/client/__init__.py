"""Vision API client package.

Provides VisionAPIClient for calling vision APIs to analyze PFD images.
Supports multiple backend implementations (OpenAI SDK, raw HTTP requests,
Anthropic SDK, Google Gemini SDK, etc.).
"""

from src.core.client.vision_client import VisionAPIClient
from src.core.client.base import BaseLLMBackend
from src.core.client.openai import OpenAIBackend
from src.core.client.requests import RequestsBackend
from src.core.client.anthropic import AnthropicBackend
from src.core.client.gemini import GeminiBackend

__all__ = [
    "VisionAPIClient",
    "BaseLLMBackend",
    "OpenAIBackend",
    "RequestsBackend",
    "AnthropicBackend",
    "GeminiBackend",
]
