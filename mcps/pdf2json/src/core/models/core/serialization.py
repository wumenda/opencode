"""Serialization utilities for model serialization."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


def model_to_dict(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        dumped = obj.model_dump(mode="json", serialize_as_any=True)
        return model_to_dict(dumped)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if isinstance(k, tuple):
                k = str(k)
            result[k] = model_to_dict(v)
        return result
    if isinstance(obj, list):
        return [model_to_dict(v) for v in obj]
    if isinstance(obj, tuple):
        return list(model_to_dict(v) for v in obj)
    return obj
