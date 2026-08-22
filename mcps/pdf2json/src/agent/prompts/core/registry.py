import os
from typing import Callable, Optional, Type

from .base import PromptBuilder

_PROMPT_REGISTRY: dict[str, dict[str, Type[PromptBuilder]]] = {}


def register_prompt(
    expert_type: str, version: str
) -> Callable[[Type[PromptBuilder]], Type[PromptBuilder]]:
    def decorator(cls: Type[PromptBuilder]) -> Type[PromptBuilder]:
        if expert_type not in _PROMPT_REGISTRY:
            _PROMPT_REGISTRY[expert_type] = {}
        _PROMPT_REGISTRY[expert_type][version] = cls
        return cls

    return decorator


def get_prompt_builder(expert_type: str, version: Optional[str] = None) -> PromptBuilder:
    versions = _PROMPT_REGISTRY.get(expert_type, {})
    if not versions:
        raise ValueError(f"No prompt builders registered for expert type: {expert_type}")

    if version is None:
        version = os.getenv(f"PROMPT_VERSION_{expert_type.upper()}", "v1")

    builder_cls = versions.get(version)
    if builder_cls is None:
        available = ", ".join(sorted(versions.keys()))
        raise ValueError(
            f"No prompt builder for {expert_type} version '{version}'. Available: {available}"
        )
    return builder_cls()


def get_available_versions(expert_type: str) -> list[str]:
    return sorted(_PROMPT_REGISTRY.get(expert_type, {}).keys())


def get_registry() -> dict[str, dict[str, Type[PromptBuilder]]]:
    return dict(_PROMPT_REGISTRY)
