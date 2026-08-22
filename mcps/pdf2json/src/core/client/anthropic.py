"""Anthropic SDK backend for LLM API calls."""

import hashlib
import importlib.util
from typing import Any, Optional

from src.core.infra.config import ReasoningEffort, Settings, ThinkingType
from src.core.infra.exceptions import APIError
from src.core.client.base import BaseLLMBackend

_EFFORT_MAP: dict[ReasoningEffort, str] = {
    ReasoningEffort.MINIMAL: "low",
    ReasoningEffort.LOW: "low",
    ReasoningEffort.MEDIUM: "medium",
    ReasoningEffort.HIGH: "high",
    ReasoningEffort.XHIGH: "max",
}


class AnthropicBackend(BaseLLMBackend):
    """Backend using the Anthropic Python SDK."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)

    def call_vision(
        self,
        base64_image: str,
        prompt: str,
        reference_base64_images: Optional[list[str]],
        call_params: dict[str, Any],
    ) -> tuple[str, Optional[str]]:
        if importlib.util.find_spec("anthropic") is None:
            raise APIError("Anthropic SDK not installed. Install with: pip install anthropic")

        client = self._get_or_create_client(
            call_params["api_key"],
            call_params["base_url"],
            call_params["timeout"],
        )

        model = call_params["model"]
        self.logger.info(f"Calling vision API (Anthropic) with model: {model}")

        content_blocks = self._build_content(prompt, base64_image, reference_base64_images)
        request_params = self._build_request_params(
            model=model,
            max_tokens=call_params["max_tokens"],
            messages=[{"role": "user", "content": content_blocks}],
            reasoning_effort=call_params["reasoning_effort"],
            thinking_type=call_params["thinking_type"],
            temperature=call_params["temperature"],
            top_p=call_params["top_p"],
        )

        try:
            if call_params["stream"]:
                return self._call_stream(client, request_params)
            response = client.messages.create(**request_params)
        except APIError:
            raise
        except Exception as e:
            raise APIError(f"Anthropic API call failed: {e}") from e

        return self._parse_response(response)

    def call_text(
        self,
        prompt: str,
        call_params: dict[str, Any],
    ) -> tuple[str, Optional[str]]:
        if importlib.util.find_spec("anthropic") is None:
            raise APIError("Anthropic SDK not installed. Install with: pip install anthropic")

        client = self._get_or_create_client(
            call_params["api_key"],
            call_params["base_url"],
            call_params["timeout"],
        )

        self.logger.info(f"Calling text-only API (Anthropic) with model: {call_params['model']}")

        request_params = self._build_request_params(
            model=call_params["model"],
            max_tokens=call_params["max_tokens"],
            messages=[{"role": "user", "content": prompt}],
            reasoning_effort=call_params["reasoning_effort"],
            thinking_type=call_params["thinking_type"],
            temperature=call_params["temperature"],
            top_p=call_params["top_p"],
        )

        try:
            if call_params["stream"]:
                return self._call_stream(client, request_params)
            response = client.messages.create(**request_params)
        except APIError:
            raise
        except Exception as e:
            raise APIError(f"Anthropic API call failed: {e}") from e

        return self._parse_response(response)

    def _build_content(
        self,
        prompt: str,
        target_base64: str,
        reference_base64_images: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": target_base64,
                },
            }
        ]
        for ref_b64 in reference_base64_images or []:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": ref_b64,
                    },
                }
            )
        content.append({"type": "text", "text": prompt})
        return content

    def _build_request_params(
        self,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        reasoning_effort: ReasoningEffort,
        thinking_type: ThinkingType = ThinkingType.AUTO,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        if thinking_type != ThinkingType.AUTO or reasoning_effort != ReasoningEffort.NONE:
            params["thinking"] = {"type": "adaptive"}
            effort = _EFFORT_MAP.get(reasoning_effort)
            if effort:
                params["output_config"] = {"effort": effort}

        if temperature is not None:
            params["temperature"] = temperature
        if top_p is not None:
            params["top_p"] = top_p

        return params

    def _parse_response(self, response: Any) -> tuple[str, Optional[str]]:
        usage = getattr(response, "usage", None)
        if usage:
            self.logger.info(
                f"Token usage: input={usage.input_tokens}, output={usage.output_tokens}"
            )

        text_parts: list[str] = []
        thinking_parts: list[str] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "thinking":
                thinking_parts.append(block.thinking)

        result_text = "".join(text_parts)
        reasoning_content = "".join(thinking_parts) if thinking_parts else None

        return self._validate_content(result_text, reasoning_content, "anthropic")

    def _get_or_create_client(self, api_key: str, base_url: str, timeout: int) -> Any:
        from anthropic import Anthropic
        import httpx

        key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        cache_key = f"anthropic:{key_hash}:{base_url}:{timeout}"
        if cache_key not in self._clients:
            kwargs: dict[str, Any] = {
                "api_key": api_key,
                "timeout": httpx.Timeout(timeout, connect=self.settings.connect_timeout),
                "max_retries": 0,  # 应用层 retry_with_backoff 已处理重试，SDK 层不叠加
            }
            if base_url:
                kwargs["base_url"] = base_url
            self._clients[cache_key] = Anthropic(**kwargs)
            self.logger.debug(f"Created new Anthropic client for {base_url}")
        return self._clients[cache_key]

    def _call_stream(
        self, client: Any, request_params: dict[str, Any]
    ) -> tuple[str, Optional[str]]:
        text_parts: list[str] = []
        thinking_parts: list[str] = []

        try:
            with client.messages.stream(**request_params) as stream:
                for event in stream:
                    if event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            text_parts.append(event.delta.text)
                        elif event.delta.type == "thinking_delta":
                            thinking_parts.append(event.delta.thinking)
        except APIError:
            raise
        except Exception as e:
            raise APIError(f"Anthropic streaming failed: {e}") from e

        result_text = "".join(text_parts)
        reasoning_content = "".join(thinking_parts) if thinking_parts else None

        return self._validate_content(result_text, reasoning_content, "anthropic_stream")
