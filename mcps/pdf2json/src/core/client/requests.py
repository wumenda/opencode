"""Raw HTTP requests backend for LLM API calls (OpenAI-compatible format)."""

import hashlib
import json
from typing import Any, Optional, cast

from src.core.infra.config import Settings
from src.core.infra.exceptions import APIError
from src.core.client.base import BaseLLMBackend


class RequestsBackend(BaseLLMBackend):
    """Backend using raw HTTP requests with OpenAI-compatible format."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)

    def call_vision(
        self,
        base64_image: str,
        prompt: str,
        reference_base64_images: Optional[list[str]],
        call_params: dict[str, Any],
    ) -> tuple[str, Optional[str]]:
        import requests

        session = self._get_or_create_session(
            call_params["api_key"],
            call_params["base_url"],
        )

        headers = {
            "Authorization": f"Bearer {call_params['api_key']}",
            "Content-Type": "application/json",
        }

        payload = self._build_request_params(
            model=call_params["model"],
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

        stream = call_params["stream"]
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}

        provider_name = call_params["provider_name"]
        model = call_params["model"]
        if provider_name != "default":
            self.logger.info(
                f"Calling vision API (requests) with model: {model} "
                f"from provider: {provider_name}"
            )
        else:
            self.logger.info("Calling vision API (requests)...")

        try:
            response = session.post(
                f"{call_params['base_url']}/chat/completions",
                headers=headers,
                json=payload,
                stream=stream,
                timeout=call_params["timeout"],
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise APIError(f"API call failed: {e}") from e

        if stream:
            return self._collect_requests_stream_content(response.iter_lines())

        result = response.json()

        usage_info = result.get("usage")
        if usage_info:
            self.logger.info(
                f"Token usage: prompt={usage_info.get('prompt_tokens')}, "
                f"completion={usage_info.get('completion_tokens')}, "
                f"total={usage_info.get('total_tokens')}"
            )

        if "error" in result:
            error_msg = result["error"]
            if isinstance(error_msg, dict):
                error_msg = error_msg.get("message", str(error_msg))
            raise APIError(f"API returned error: {error_msg}")

        if "choices" in result and len(result["choices"]) > 0:
            choice = result["choices"][0]
            message = choice.get("message", {})
            content = message.get("content", "")
            reasoning_content = message.get("reasoning_content")

            return self._validate_content(
                cast(Optional[str], content), reasoning_content, "requests_vision"
            )

        raise APIError(f"Unexpected API response format: {result.keys()}")

    def call_text(
        self,
        prompt: str,
        call_params: dict[str, Any],
    ) -> tuple[str, Optional[str]]:
        import requests

        session = self._get_or_create_session(
            call_params["api_key"],
            call_params["base_url"],
        )

        url = f"{call_params['base_url']}/chat/completions"
        headers = {
            "Authorization": f"Bearer {call_params['api_key']}",
            "Content-Type": "application/json",
        }
        payload = self._build_request_params(
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

        stream = call_params["stream"]
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}

        self.logger.info(f"Calling text-only API with model: {call_params['model']}")

        try:
            resp = session.post(
                url, headers=headers, json=payload, stream=stream, timeout=self.settings.timeout
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise APIError(f"API call failed: {e}") from e

        if stream:
            return self._collect_requests_stream_content(resp.iter_lines())

        data = resp.json()

        usage_info = data.get("usage")
        if usage_info:
            self.logger.info(
                f"Token usage: prompt={usage_info.get('prompt_tokens')}, "
                f"completion={usage_info.get('completion_tokens')}, "
                f"total={usage_info.get('total_tokens')}"
            )

        choices = data.get("choices") or []
        if not choices:
            raise APIError(f"API 返回无 choices: {data}")
        message = choices[0].get("message") or {}
        result_text = message.get("content")
        reasoning_content = message.get("reasoning_content")
        return self._validate_content(
            cast(Optional[str], result_text), reasoning_content, "requests_text"
        )

    def _get_or_create_session(self, api_key: str, base_url: str) -> Any:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        cache_key = f"{key_hash}:{base_url}"
        if cache_key not in self._clients:
            session = requests.Session()
            retry_strategy = Retry(
                total=0,  # 应用层 retry_with_backoff 已处理重试，HTTP 层不叠加
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["POST"],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            self._clients[cache_key] = session
            self.logger.debug(f"Created new requests session for {base_url}")
        return self._clients[cache_key]

    def _collect_requests_stream_content(self, lines: Any) -> tuple[str, Optional[str]]:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        last_usage: Optional[dict[str, Any]] = None
        for raw_line in lines:
            if isinstance(raw_line, bytes):
                line = raw_line.decode("utf-8", errors="replace").strip()
            else:
                line = str(raw_line).strip()

            if not line or not line.startswith("data:"):
                continue

            data_text = line[5:].strip()
            if data_text == "[DONE]":
                break

            try:
                event = json.loads(data_text)
            except json.JSONDecodeError:
                self.logger.warning(f"skip malformed SSE line: {data_text[:100]}")
                continue
            if "error" in event:
                error_msg = event["error"]
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", str(error_msg))
                raise APIError(f"API returned error: {error_msg}")

            event_usage = event.get("usage")
            if event_usage:
                last_usage = event_usage

            for choice in event.get("choices", []):
                content = choice.get("delta", {}).get("content")
                if content:
                    content_parts.append(content)
                reasoning_content = choice.get("delta", {}).get("reasoning_content")
                if reasoning_content:
                    reasoning_parts.append(reasoning_content)

        if last_usage:
            self.logger.info(
                f"Token usage: prompt={last_usage.get('prompt_tokens')}, "
                f"completion={last_usage.get('completion_tokens')}, "
                f"total={last_usage.get('total_tokens')}"
            )

        result_text = "".join(content_parts)
        reasoning_text = "".join(reasoning_parts) if reasoning_parts else None
        return self._validate_content(result_text, reasoning_text, "requests_stream")
