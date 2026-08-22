"""Vision API client for PFD analysis.

Provides a unified client for calling vision APIs to analyze PFD images.
Delegates actual API calls to pluggable backends.
"""

import importlib.util
import io
import base64
import os
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from src.core.infra.config import Settings, ProviderConfig, ExpertConfig
from src.core.infra.exceptions import APIError, ImageProcessingError
from src.core.io.image_io import encode_image as _encode_image
from src.core.infra.logging import LoggerMixin
from src.core.client.base import BaseLLMBackend
from src.core.client.openai import OpenAIBackend
from src.core.client.requests import RequestsBackend
from src.core.client.anthropic import AnthropicBackend
from src.core.client.gemini import GeminiBackend
from src.core.client.resilience import retry_with_backoff, get_breaker, CircuitOpenError


def _parse_fallbacks() -> list[tuple[str, str]]:
    """解析 PFD_FALLBACKS=provider1:model1,provider2:model2。"""
    raw = os.environ.get("PFD_FALLBACKS", "").strip()
    out = []
    if not raw:
        return out
    for item in raw.split(","):
        item = item.strip()
        if ":" in item:
            p, m = item.split(":", 1)
            out.append((p.strip(), m.strip()))
    return out


class VisionAPIClient(LoggerMixin):
    """Client for calling vision APIs to analyze PFD images.

    Handles image encoding, resizing, API calls, and response parsing.
    Delegates actual API calls to backend implementations.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._encoding_cache: dict[str, tuple[str, int, int]] = {}
        self._metadata_cache: dict[str, dict[str, Any]] = {}
        self._backends: dict[str, BaseLLMBackend] = {}

    def _get_backend(self, api_type: str = "openai", use_openai: bool = True) -> BaseLLMBackend:
        """Get or create the appropriate backend based on api_type.

        Args:
            api_type: API protocol type - "openai", "anthropic", or "gemini".
            use_openai: Legacy flag, only used when api_type="openai".
                        Falls back to requests backend if OpenAI SDK is not installed.
        """
        if api_type == "anthropic":
            if "anthropic" not in self._backends:
                self._backends["anthropic"] = AnthropicBackend(self.settings)
            return self._backends["anthropic"]

        if api_type == "gemini":
            if "gemini" not in self._backends:
                self._backends["gemini"] = GeminiBackend(self.settings)
            return self._backends["gemini"]

        if use_openai:
            if importlib.util.find_spec("openai") is None:
                self.logger.warning("OpenAI SDK not available, falling back to requests backend")
                use_openai = False

        backend_key = "openai" if use_openai else "requests"
        if backend_key not in self._backends:
            if use_openai:
                self._backends[backend_key] = OpenAIBackend(self.settings)
            else:
                self._backends[backend_key] = RequestsBackend(self.settings)
        return self._backends[backend_key]

    def _resolve_call_params(
        self,
        provider_config: Optional[ProviderConfig] = None,
        expert_config: Optional[ExpertConfig] = None,
    ) -> dict[str, Any]:
        return {
            "api_key": provider_config.api_key if provider_config else self.settings.api_key,
            "base_url": provider_config.base_url if provider_config else self.settings.base_url,
            "model": expert_config.model if expert_config else self.settings.model,
            "max_tokens": self.settings.max_tokens,
            "timeout": expert_config.timeout if expert_config else self.settings.timeout,
            "provider_name": provider_config.key if provider_config else "default",
            "api_type": provider_config.api_type if provider_config else "openai",
            "reasoning_effort": (
                expert_config.reasoning_effort if expert_config else self.settings.reasoning_effort
            ),
            "thinking_type": (
                expert_config.thinking_type if expert_config else self.settings.thinking_type
            ),
            "stream": expert_config.stream if expert_config else self.settings.stream,
            "temperature": (
                expert_config.temperature
                if expert_config and expert_config.temperature is not None
                else self.settings.temperature
            ),
            "top_p": (
                expert_config.top_p
                if expert_config and expert_config.top_p is not None
                else self.settings.top_p
            ),
            "seed": (
                expert_config.seed
                if expert_config and expert_config.seed is not None
                else self.settings.seed
            ),
            "response_format": (
                expert_config.response_format
                if expert_config and expert_config.response_format is not None
                else self.settings.response_format
            ),
            "prefix_caching": (
                expert_config.enable_prefix_caching
                if expert_config and expert_config.enable_prefix_caching is not None
                else self.settings.enable_prefix_caching
            ),
        }

    def resize_image_if_needed(
        self,
        image_path: Path,
        max_pixels: Optional[int] = None,
        max_dimension: Optional[int] = None,
    ) -> tuple[str, bool, int, int, int, int]:
        max_pixels = max_pixels or self.settings.max_image_pixels
        max_dimension = max_dimension or self.settings.max_image_size

        cache_key = f"{image_path}:{max_pixels}:{max_dimension}"
        if cache_key in self._encoding_cache:
            cached_b64, cached_w, cached_h = self._encoding_cache[cache_key]
            try:
                with Image.open(image_path) as img:
                    orig_w, orig_h = img.size
                    was_resized = orig_w != cached_w or orig_h != cached_h
                    return cached_b64, was_resized, orig_w, orig_h, cached_w, cached_h
            except Exception as e:
                self.logger.warning(f"Cache validation failed, clearing cache entry: {e}")

        try:
            with Image.open(image_path) as img:
                original_width, original_height = img.size
                original_pixels = original_width * original_height

                needs_resize = False
                new_width, new_height = original_width, original_height

                if original_pixels > max_pixels:
                    scale = (max_pixels / original_pixels) ** 0.5
                    new_width = int(original_width * scale)
                    new_height = int(original_height * scale)
                    needs_resize = True

                max_original_dim = max(original_width, original_height)
                if max_original_dim > max_dimension:
                    scale = max_dimension / max_original_dim
                    new_width = int(original_width * scale)
                    new_height = int(original_height * scale)
                    needs_resize = True

                if not needs_resize:
                    result_b64 = _encode_image(image_path)
                    self._encoding_cache[cache_key] = (result_b64, original_width, original_height)
                    return (
                        result_b64,
                        False,
                        original_width,
                        original_height,
                        original_width,
                        original_height,
                    )

                self.logger.info(
                    f"Resizing image: {original_width}x{original_height} -> {new_width}x{new_height}"
                )

                img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

                buffer = io.BytesIO()
                if img_resized.mode in ("RGBA", "P"):
                    img_resized = img_resized.convert("RGB")
                img_resized.save(buffer, format="PNG", optimize=True)

                result_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
                self._encoding_cache[cache_key] = (result_b64, new_width, new_height)
                return result_b64, True, original_width, original_height, new_width, new_height

        except Exception as e:
            raise ImageProcessingError(f"Failed to resize image: {e}") from e

    def _get_image_metadata(
        self,
        image_path: Path,
        was_resized: bool,
        orig_w: int,
        orig_h: int,
        new_w: int,
        new_h: int,
    ) -> dict[str, Any]:
        dynamic_fields = {
            "original_width": orig_w,
            "original_height": orig_h,
            "processed_width": new_w,
            "processed_height": new_h,
            "was_resized": was_resized,
            "original_pixels": orig_w * orig_h,
            "processed_pixels": new_w * new_h,
        }

        cache_key = str(image_path)
        if cache_key in self._metadata_cache:
            result = self._metadata_cache[cache_key].copy()
            result.update(dynamic_fields)
            return result

        try:
            with Image.open(image_path) as img:
                file_size_bytes = image_path.stat().st_size
                file_size_mb = file_size_bytes / (1024 * 1024)

                img_format = img.format or "PNG"

                dpi = None
                if img.info.get("dpi"):
                    dpi_value = img.info["dpi"]
                    if isinstance(dpi_value, tuple):
                        dpi = int(dpi_value[0])
                    else:
                        dpi = int(dpi_value)

                color_mode = img.mode

                bit_depth_map = {
                    "1": 1,
                    "L": 8,
                    "P": 8,
                    "RGB": 24,
                    "RGBA": 32,
                    "CMYK": 32,
                    "YCbCr": 24,
                    "LAB": 24,
                    "HSV": 24,
                    "I": 32,
                    "F": 32,
                }
                bit_depth = bit_depth_map.get(color_mode, 8)

                base_metadata = {
                    "file_path": str(image_path),
                    "format": img_format,
                    "dpi": dpi,
                    "color_mode": color_mode,
                    "bit_depth": bit_depth,
                    "file_size_mb": round(file_size_mb, 2),
                }
                self._metadata_cache[cache_key] = base_metadata

                result = base_metadata.copy()
                result.update(dynamic_fields)
                return result

        except Exception as e:
            self.logger.warning(f"Failed to get image metadata: {e}")
            return {
                "file_path": str(image_path),
                "format": "PNG",
                "dpi": None,
                "color_mode": "RGB",
                "bit_depth": 24,
                "file_size_mb": None,
                **dynamic_fields,
            }

    def call_api(
        self,
        image_path: str,
        prompt: str,
        use_openai: bool = True,
        reference_image_paths: Optional[list[str]] = None,
        max_dimension: Optional[int] = None,
        provider_config: Optional[ProviderConfig] = None,
        expert_config: Optional[ExpertConfig] = None,
    ) -> tuple[str, dict[str, Any], Optional[str]]:
        image_path_obj = Path(image_path)
        if not image_path_obj.exists():
            raise APIError(f"Image file not found: {image_path}")

        base64_image, was_resized, orig_w, orig_h, new_w, new_h = self.resize_image_if_needed(
            image_path_obj, max_dimension=max_dimension
        )
        self.logger.debug(f"Image encoded, size: {len(base64_image)} chars")

        image_metadata = self._get_image_metadata(
            image_path_obj, was_resized, orig_w, orig_h, new_w, new_h
        )

        reference_base64_images: list[str] = []
        for ref_path in reference_image_paths or []:
            ref_image_path = Path(ref_path)
            if not ref_image_path.exists():
                self.logger.warning(f"Reference image not found, skipping: {ref_path}")
                continue

            try:
                ref_b64, _, _, _, _, _ = self.resize_image_if_needed(
                    ref_image_path, max_dimension=max_dimension
                )
                reference_base64_images.append(ref_b64)
            except Exception as e:
                self.logger.warning(f"Failed to encode reference image {ref_path}: {e}")

        call_params = self._resolve_call_params(provider_config, expert_config)

        # 构建候选 provider 列表：主 provider + PFD_FALLBACKS 中的备用
        candidates = [(call_params["provider_name"], call_params["model"])]
        for fp, fm in _parse_fallbacks():
            if fp != call_params["provider_name"]:
                candidates.append((fp, fm))

        retrying = retry_with_backoff(
            max_attempts=self.settings.max_retries, base_delay=1.0, logger=self.logger
        )
        last_err = None
        for cand_provider, cand_model in candidates:
            cand_pc = self.settings.get_provider_config(cand_provider)
            if not cand_pc:
                continue
            cand_params = dict(call_params)
            cand_params["provider_name"] = cand_pc.name
            cand_params["api_key"] = cand_pc.api_key
            cand_params["base_url"] = cand_pc.base_url
            cand_params["api_type"] = cand_pc.api_type
            cand_params["model"] = cand_model
            cand_backend = self._get_backend(api_type=cand_pc.api_type, use_openai=use_openai)
            breaker = get_breaker(cand_pc.name)
            try:
                breaker.guard()
                content, reasoning_content = retrying(cand_backend.call_vision)(
                    base64_image, prompt, reference_base64_images, cand_params
                )
                breaker.record_success()
                from src.core.infra.metrics import VLM_CALLS_TOTAL
                VLM_CALLS_TOTAL.inc(provider=cand_pc.name, expert="vision")
                return content, image_metadata, reasoning_content
            except Exception as e:
                if isinstance(e, CircuitOpenError):
                    last_err = e
                    self.logger.warning(
                        f"provider {cand_pc.name} circuit open; trying next fallback"
                    )
                    continue
                breaker.record_failure()
                from src.core.infra.metrics import VLM_FAILURES_TOTAL
                VLM_FAILURES_TOTAL.inc(provider=cand_pc.name)
                last_err = e
                self.logger.warning(
                    f"provider {cand_pc.name} failed: {e}; trying next fallback"
                )
                continue
        if last_err is not None:
            raise last_err
        raise APIError(
            "No available VLM provider. Check config/providers.yaml and provider API keys."
        )

    def call_api_with_image(
        self,
        image: Image.Image,
        prompt: str,
        use_openai: bool = True,
        provider_config: Optional[ProviderConfig] = None,
        expert_config: Optional[ExpertConfig] = None,
        max_dimension: Optional[int] = None,
    ) -> tuple[str, dict[str, Any], Optional[str]]:
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")

        max_dimension = max_dimension or self.settings.max_image_size

        original_width, original_height = image.size
        new_width, new_height = original_width, original_height

        max_pixels = self.settings.max_image_pixels
        original_pixels = original_width * original_height
        needs_resize = False

        if original_pixels > max_pixels:
            scale = (max_pixels / original_pixels) ** 0.5
            new_width = int(original_width * scale)
            new_height = int(original_height * scale)
            needs_resize = True

        max_original_dim = max(original_width, original_height)
        if max_original_dim > max_dimension:
            scale = max_dimension / max_original_dim
            new_width = int(original_width * scale)
            new_height = int(original_height * scale)
            needs_resize = True

        if needs_resize:
            self.logger.info(
                f"Resizing in-memory image: {original_width}x{original_height} -> {new_width}x{new_height}"
            )
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        base64_image = base64.b64encode(buffer.getvalue()).decode("utf-8")

        call_params = self._resolve_call_params(provider_config, expert_config)
        backend = self._get_backend(api_type=call_params["api_type"], use_openai=use_openai)
        retrying = retry_with_backoff(
            max_attempts=self.settings.max_retries, base_delay=1.0, logger=self.logger
        )
        content, reasoning_content = retrying(backend.call_vision)(
            base64_image, prompt, None, call_params
        )

        image_metadata = {
            "file_path": "memory",
            "original_width": original_width,
            "original_height": original_height,
            "processed_width": new_width,
            "processed_height": new_height,
            "was_resized": needs_resize,
            "original_pixels": original_pixels,
            "processed_pixels": new_width * new_height,
            "format": "PNG",
            "dpi": None,
            "color_mode": image.mode,
            "bit_depth": 24,
            "file_size_mb": None,
        }
        return content, image_metadata, reasoning_content

    def call_api_with_expert_config(
        self,
        image_path: str,
        prompt: str,
        provider_config: ProviderConfig,
        expert_config: ExpertConfig,
        use_openai: bool = True,
        reference_image_paths: Optional[list[str]] = None,
        max_dimension: Optional[int] = None,
    ) -> tuple[str, dict[str, Any], Optional[str]]:
        return self.call_api(
            image_path=image_path,
            prompt=prompt,
            use_openai=use_openai,
            reference_image_paths=reference_image_paths,
            max_dimension=max_dimension,
            provider_config=provider_config,
            expert_config=expert_config,
        )

    def call_api_text_only(
        self,
        prompt: str,
        provider_config: Optional[ProviderConfig] = None,
        expert_config: Optional[ExpertConfig] = None,
    ) -> tuple[str, Optional[str]]:
        call_params = self._resolve_call_params(provider_config, expert_config)
        backend = self._get_backend(api_type=call_params["api_type"])
        retrying = retry_with_backoff(
            max_attempts=self.settings.max_retries, base_delay=1.0, logger=self.logger
        )
        return retrying(backend.call_text)(prompt, call_params)
