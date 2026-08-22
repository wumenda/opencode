"""Base class for LLM API backends."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

from src.core.infra.config import ReasoningEffort, Settings, ThinkingType
from src.core.infra.logging import LoggerMixin


class BaseLLMBackend(LoggerMixin, ABC):
    """Abstract base class for LLM API backends.

    Each backend implements a specific API protocol (OpenAI, Anthropic, etc.)
    and handles request formatting, transport, and response parsing.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._clients: dict[str, Any] = {}

    @abstractmethod
    def call_vision(
        self,
        base64_image: str,
        prompt: str,
        reference_base64_images: Optional[list[str]],
        call_params: dict[str, Any],
    ) -> tuple[str, Optional[str]]:
        """Call vision API with an image and prompt.

        Args:
            base64_image: Base64-encoded image.
            prompt: Text prompt.
            reference_base64_images: Optional reference images for few-shot.
            call_params: Resolved call parameters dict.

        Returns:
            Tuple of (content text, reasoning_content or None).
        """

    @abstractmethod
    def call_text(
        self,
        prompt: str,
        call_params: dict[str, Any],
    ) -> tuple[str, Optional[str]]:
        """Call text-only API.

        Args:
            prompt: Text prompt.
            call_params: Resolved call parameters dict.

        Returns:
            Tuple of (content text, reasoning_content or None).
        """

    def _build_message_content(
        self,
        prompt: str,
        target_base64: str,
        reference_base64_images: Optional[list[str]] = None,
        prefix_caching: bool = True,
    ) -> list[dict[str, Any]]:
        """Build OpenAI-format message content with configurable ordering for prefix caching."""
        image_items: list[dict[str, Any]] = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{target_base64}"},
            }
        ]
        for ref_b64 in reference_base64_images or []:
            image_items.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{ref_b64}"},
                }
            )

        text_item: dict[str, Any] = {"type": "text", "text": prompt}

        if prefix_caching:
            return [text_item, *image_items]
        return [*image_items, text_item]

    def _build_request_params(
        self,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        reasoning_effort: ReasoningEffort,
        thinking_type: ThinkingType = ThinkingType.AUTO,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        seed: Optional[int] = None,
        response_format: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Build OpenAI-format request parameters."""
        params: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if thinking_type != ThinkingType.AUTO or reasoning_effort != ReasoningEffort.NONE:
            params["thinking"] = {"type": thinking_type.value}
        if reasoning_effort != ReasoningEffort.NONE:
            params["reasoning_effort"] = reasoning_effort.value
        if temperature is not None:
            params["temperature"] = temperature
        if top_p is not None:
            params["top_p"] = top_p
        if seed is not None:
            params["seed"] = seed
        if response_format is not None:
            params["response_format"] = response_format
        return params

    def _validate_content(
        self,
        result_text: Optional[str],
        reasoning_content: Optional[str],
        context_label: str = "",
    ) -> tuple[str, Optional[str]]:
        """Validate API response content is non-empty and contains JSON.

        Raises APIError when content is empty/None, or when content has no
        JSON opening brace while reasoning_content exists (indicating the
        model's thinking consumed the output token budget). The latter case
        is rescued by falling back to reasoning_content so downstream JSON
        recovery can attempt to parse it.
        """
        from src.core.infra.exceptions import APIError

        if result_text is None or not result_text.strip():
            hint = ""
            if reasoning_content:
                hint = (
                    f" (reasoning_content has {len(reasoning_content)} chars — "
                    f"thinking may have consumed all output tokens)"
                )
                self._save_orphaned_thinking(reasoning_content, context_label)
            raise APIError(f"API returned empty content{hint}")

        if "{" not in result_text and reasoning_content and "{" in reasoning_content:
            self.logger.warning(
                f"Content has no JSON brace but reasoning_content "
                f"({len(reasoning_content)} chars) does — falling back to "
                f"reasoning_content for parsing (context: {context_label})"
            )
            self._save_orphaned_thinking(reasoning_content, context_label)
            return reasoning_content, reasoning_content

        return result_text, reasoning_content

    def _save_orphaned_thinking(self, reasoning_content: str, context_label: str = "") -> None:
        try:
            output_dir = self.settings.thinking_output_dir
            output_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            label = f"_{context_label}" if context_label else ""
            filename = f"{timestamp}{label}_orphaned_thinking.md"
            output_path = output_dir / filename

            content = "# Orphaned Thinking Content (empty API response)\n\n"
            content += f"**Timestamp**: {datetime.now().isoformat()}\n"
            content += "**Reason**: API returned empty content but reasoning_content exists\n"
            content += f"**Reasoning length**: {len(reasoning_content)} chars\n\n"
            content += "---\n\n"
            content += reasoning_content

            output_path.write_text(content, encoding="utf-8")
            self.logger.info(f"Saved orphaned thinking content to: {output_path}")
        except Exception as e:
            self.logger.warning(f"Failed to save orphaned thinking content: {e}")
