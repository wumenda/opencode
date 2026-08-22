"""OpenAI SDK backend for LLM API calls."""

import hashlib
import importlib.util
from typing import Any, Optional, cast

from src.core.infra.config import Settings
from src.core.infra.exceptions import APIError
from src.core.client.base import BaseLLMBackend


class OpenAIBackend(BaseLLMBackend):
    """Backend using the OpenAI Python SDK."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)

    def call_vision(
        self,
        base64_image: str,
        prompt: str,
        reference_base64_images: Optional[list[str]],
        call_params: dict[str, Any],
    ) -> tuple[str, Optional[str]]:
        if importlib.util.find_spec("openai") is None:
            raise APIError("OpenAI SDK not installed. Install with: pip install openai")

        client = self._get_or_create_openai_client(
            call_params["api_key"],
            call_params["base_url"],
            call_params["timeout"],
        )

        provider_name = call_params["provider_name"]
        model = call_params["model"]
        if provider_name != "default":
            self.logger.info(
                f"Calling vision API (OpenAI client) with model: {model} "
                f"from provider: {provider_name}"
            )
        else:
            self.logger.info("Calling vision API (OpenAI client)...")

        request_params = self._build_request_params(
            model=model,
            max_tokens=call_params["max_tokens"],
            messages=[
                {
                    "role": "user",
                    "content": self._build_message_content(
                        prompt=prompt,
                        target_base64=base64_image,
                        reference_base64_images=reference_base64_images,
                        prefix_caching=call_params["prefix_caching"],
                    ),
                }
            ],
            reasoning_effort=call_params["reasoning_effort"],
            thinking_type=call_params["thinking_type"],
            temperature=call_params["temperature"],
            top_p=call_params["top_p"],
            seed=call_params["seed"],
            response_format=call_params["response_format"],
        )

        extra_body = None
        if "thinking" in request_params:
            extra_body = {"thinking": request_params.pop("thinking")}

        try:
            if call_params["stream"]:
                response_stream = client.chat.completions.create(
                    **{
                        **request_params,
                        "stream": True,
                        "stream_options": {"include_usage": True},
                    },
                    **({"extra_body": extra_body} if extra_body else {}),
                )
                return self._collect_openai_stream_content(response_stream)

            response = client.chat.completions.create(
                **request_params,
                **({"extra_body": extra_body} if extra_body else {}),
            )
        except APIError:
            raise
        except Exception as e:
            raise APIError(f"OpenAI API call failed: {e}") from e

        usage = getattr(response, "usage", None)
        if usage:
            self.logger.info(
                f"Token usage: prompt={usage.prompt_tokens}, "
                f"completion={usage.completion_tokens}, "
                f"total={usage.total_tokens}"
            )

        message = response.choices[0].message
        result_text = message.content
        reasoning_content = getattr(message, "reasoning_content", None)
        return self._validate_content(
            cast(Optional[str], result_text), reasoning_content, "openai_vision"
        )

    def call_text(
        self,
        prompt: str,
        call_params: dict[str, Any],
    ) -> tuple[str, Optional[str]]:
        if importlib.util.find_spec("openai") is None:
            raise APIError("OpenAI SDK not installed. Install with: pip install openai")

        client = self._get_or_create_openai_client(
            call_params["api_key"],
            call_params["base_url"],
            call_params["timeout"],
        )

        self.logger.info(f"Calling text-only API with model: {call_params['model']}")

        request_params = self._build_request_params(
            model=call_params["model"],
            max_tokens=call_params["max_tokens"],
            messages=[{"role": "user", "content": prompt}],
            reasoning_effort=call_params["reasoning_effort"],
            thinking_type=call_params["thinking_type"],
            temperature=call_params["temperature"],
            top_p=call_params["top_p"],
            seed=call_params["seed"],
            response_format=call_params["response_format"],
        )

        extra_body = None
        if "thinking" in request_params:
            extra_body = {"thinking": request_params.pop("thinking")}

        try:
            if call_params["stream"]:
                response_stream = client.chat.completions.create(
                    **{
                        **request_params,
                        "stream": True,
                        "stream_options": {"include_usage": True},
                    },
                    **({"extra_body": extra_body} if extra_body else {}),
                )
                return self._collect_openai_stream_content(response_stream)

            response = client.chat.completions.create(
                **request_params,
                **({"extra_body": extra_body} if extra_body else {}),
            )
        except APIError:
            raise
        except Exception as e:
            raise APIError(f"OpenAI API call failed: {e}") from e

        usage = getattr(response, "usage", None)
        if usage:
            self.logger.info(
                f"Token usage: prompt={usage.prompt_tokens}, "
                f"completion={usage.completion_tokens}, "
                f"total={usage.total_tokens}"
            )

        message = response.choices[0].message
        result_text = message.content
        reasoning_content = getattr(message, "reasoning_content", None)
        return self._validate_content(
            cast(Optional[str], result_text), reasoning_content, "openai_text"
        )

    def _get_or_create_openai_client(self, api_key: str, base_url: str, timeout: int) -> Any:
        from openai import OpenAI
        import httpx

        key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        cache_key = f"{key_hash}:{base_url}:{timeout}"
        if cache_key not in self._clients:
            self._clients[cache_key] = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=httpx.Timeout(timeout, connect=self.settings.connect_timeout),
                max_retries=0,  # 应用层 retry_with_backoff 已处理重试，SDK 层不叠加
            )
            self.logger.debug(f"Created new OpenAI client for {base_url}")
        return self._clients[cache_key]

    def _collect_openai_stream_content(self, stream: Any) -> tuple[str, Optional[str]]:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        last_usage: Optional[Any] = None
        for chunk in stream:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage:
                last_usage = chunk_usage
            choices = getattr(chunk, "choices", None) or []
            for choice in choices:
                delta = getattr(choice, "delta", None)
                content = getattr(delta, "content", None)
                if content:
                    content_parts.append(content)
                reasoning_content = getattr(delta, "reasoning_content", None)
                if reasoning_content:
                    reasoning_parts.append(reasoning_content)

        if last_usage:
            self.logger.info(
                f"Token usage: prompt={last_usage.prompt_tokens}, "
                f"completion={last_usage.completion_tokens}, "
                f"total={last_usage.total_tokens}"
            )

        result_text = "".join(content_parts)
        reasoning_text = "".join(reasoning_parts) if reasoning_parts else None
        return self._validate_content(result_text, reasoning_text, "openai_stream")
