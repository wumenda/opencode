"""Google Gemini SDK backend for LLM API calls."""

import base64
import hashlib
import importlib.util
from typing import Any, Optional

from src.core.infra.config import ReasoningEffort, Settings, ThinkingType
from src.core.infra.exceptions import APIError
from src.core.client.base import BaseLLMBackend


class GeminiBackend(BaseLLMBackend):
    """Backend using the Google GenAI Python SDK."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)

    def call_vision(
        self,
        base64_image: str,
        prompt: str,
        reference_base64_images: Optional[list[str]],
        call_params: dict[str, Any],
    ) -> tuple[str, Optional[str]]:
        if importlib.util.find_spec("google.genai") is None:
            raise APIError("Google GenAI SDK not installed. Install with: pip install google-genai")

        client = self._get_or_create_client(call_params["api_key"])

        model = call_params["model"]
        self.logger.info(f"Calling vision API (Gemini) with model: {model}")

        contents = self._build_vision_contents(prompt, base64_image, reference_base64_images)
        config = self._build_config(
            max_tokens=call_params["max_tokens"],
            reasoning_effort=call_params["reasoning_effort"],
            thinking_type=call_params["thinking_type"],
            temperature=call_params["temperature"],
            top_p=call_params["top_p"],
            seed=call_params["seed"],
            response_format=call_params["response_format"],
        )

        try:
            if call_params["stream"]:
                return self._call_stream(client, model, contents, config)
            response = client.models.generate_content(
                model=model, contents=contents, config=config
            )
        except APIError:
            raise
        except Exception as e:
            raise APIError(f"Gemini API call failed: {e}") from e

        return self._parse_response(response)

    def call_text(
        self,
        prompt: str,
        call_params: dict[str, Any],
    ) -> tuple[str, Optional[str]]:
        if importlib.util.find_spec("google.genai") is None:
            raise APIError("Google GenAI SDK not installed. Install with: pip install google-genai")

        client = self._get_or_create_client(call_params["api_key"])

        self.logger.info(f"Calling text-only API (Gemini) with model: {call_params['model']}")

        config = self._build_config(
            max_tokens=call_params["max_tokens"],
            reasoning_effort=call_params["reasoning_effort"],
            thinking_type=call_params["thinking_type"],
            temperature=call_params["temperature"],
            top_p=call_params["top_p"],
            seed=call_params["seed"],
            response_format=call_params["response_format"],
        )

        try:
            if call_params["stream"]:
                return self._call_stream(client, call_params["model"], prompt, config)
            response = client.models.generate_content(
                model=call_params["model"], contents=prompt, config=config
            )
        except APIError:
            raise
        except Exception as e:
            raise APIError(f"Gemini API call failed: {e}") from e

        return self._parse_response(response)

    def _build_vision_contents(
        self,
        prompt: str,
        target_base64: str,
        reference_base64_images: Optional[list[str]] = None,
    ) -> list[Any]:
        from google.genai import types

        parts: list[Any] = []

        image_bytes = base64.b64decode(target_base64)
        parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))

        for ref_b64 in reference_base64_images or []:
            ref_bytes = base64.b64decode(ref_b64)
            parts.append(types.Part.from_bytes(data=ref_bytes, mime_type="image/png"))

        parts.append(types.Part.from_text(text=prompt))

        return [types.Content(role="user", parts=parts)]

    def _build_config(
        self,
        max_tokens: int,
        reasoning_effort: ReasoningEffort,
        thinking_type: ThinkingType = ThinkingType.AUTO,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        seed: Optional[int] = None,
        response_format: Optional[dict[str, str]] = None,
    ) -> Any:
        from google.genai import types

        config_kwargs: dict[str, Any] = {
            "max_output_tokens": max_tokens,
        }

        if thinking_type != ThinkingType.AUTO or reasoning_effort != ReasoningEffort.NONE:
            budget = max_tokens
            if reasoning_effort == ReasoningEffort.LOW:
                budget = min(budget, 4096)
            elif reasoning_effort == ReasoningEffort.MEDIUM:
                budget = min(budget, 16384)
            elif reasoning_effort == ReasoningEffort.HIGH:
                budget = min(budget, 32768)
            elif reasoning_effort == ReasoningEffort.XHIGH:
                budget = min(budget, 65536)
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=budget,
            )

        if temperature is not None:
            config_kwargs["temperature"] = temperature
        if top_p is not None:
            config_kwargs["top_p"] = top_p
        if seed is not None:
            config_kwargs["seed"] = seed
        if response_format is not None:
            if response_format.get("type") == "json_object":
                config_kwargs["response_mime_type"] = "application/json"
            elif response_format.get("type") == "text":
                config_kwargs["response_mime_type"] = "text/plain"

        return types.GenerateContentConfig(**config_kwargs)

    def _parse_response(self, response: Any) -> tuple[str, Optional[str]]:
        usage = getattr(response, "usage_metadata", None)
        if usage:
            self.logger.info(
                f"Token usage: prompt={usage.prompt_token_count}, "
                f"completion={usage.candidates_token_count}, "
                f"total={usage.total_token_count}"
            )

        text_parts: list[str] = []
        thinking_parts: list[str] = []

        if response.candidates:
            for candidate in response.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, "text") and part.text:
                            if getattr(part, "thought", False):
                                thinking_parts.append(part.text)
                            else:
                                text_parts.append(part.text)

        result_text = "".join(text_parts)
        reasoning_content = "".join(thinking_parts) if thinking_parts else None

        return self._validate_content(result_text, reasoning_content, "gemini")

    def _get_or_create_client(self, api_key: str) -> Any:
        from google import genai

        key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        cache_key = f"gemini:{key_hash}"
        if cache_key not in self._clients:
            self._clients[cache_key] = genai.Client(api_key=api_key)
            self.logger.debug("Created new Gemini client")
        return self._clients[cache_key]

    def _call_stream(
        self, client: Any, model: str, contents: Any, config: Any
    ) -> tuple[str, Optional[str]]:
        text_parts: list[str] = []
        thinking_parts: list[str] = []

        try:
            for chunk in client.models.generate_content_stream(
                model=model, contents=contents, config=config
            ):
                if chunk.candidates:
                    for candidate in chunk.candidates:
                        if candidate.content and candidate.content.parts:
                            for part in candidate.content.parts:
                                if hasattr(part, "text") and part.text:
                                    if getattr(part, "thought", False):
                                        thinking_parts.append(part.text)
                                    else:
                                        text_parts.append(part.text)
        except APIError:
            raise
        except Exception as e:
            raise APIError(f"Gemini streaming failed: {e}") from e

        result_text = "".join(text_parts)
        reasoning_content = "".join(thinking_parts) if thinking_parts else None

        return self._validate_content(result_text, reasoning_content, "gemini_stream")
