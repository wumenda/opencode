"""Safe model construction — drop failing fields instead of whole objects.

When a Pydantic model fails validation due to one or more bad fields,
``safe_model_validate`` removes the offending **optional** fields and retries.
Required fields (those without defaults) cause the function to return ``None``
so the caller can skip the object entirely.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_logger = logging.getLogger(__name__)


def safe_model_validate(
    model_cls: type[T],
    data: Any,
    *,
    required_fields: set[str] | None = None,
    logger: logging.Logger | None = None,
) -> T | None:
    """Construct a Pydantic model, dropping fields that fail validation.

    Behaviour:
    - Optional field fails → remove it, retry with remaining data.
    - Required field fails → return ``None`` (object cannot be constructed).
    - Extra fields (``extra="forbid"``) → silently dropped.
    - Non-dict input → return ``None``.

    Parameters
    ----------
    model_cls
        Pydantic model class to construct.
    data
        Input data (expected dict; non-dict returns ``None``).
    required_fields
        Extra field names to treat as required (in addition to fields that
        have no default in the model definition).
    logger
        Optional logger; if ``None`` uses a module-level logger.
    """
    if not isinstance(data, dict):
        return None

    log = logger or _logger

    # Collect required field names from the model definition.
    required: set[str] = set()
    for fname, finfo in model_cls.model_fields.items():
        if finfo.is_required():
            required.add(fname)
    if required_fields:
        required |= required_fields

    cleaned = dict(data)

    # Worst case: drop every optional field one by one.
    for _ in range(len(cleaned) + 1):
        try:
            return model_cls(**cleaned)
        except ValidationError as e:
            dropped = False
            for err in e.errors():
                loc = err.get("loc", ())
                if not loc:
                    continue
                fname = loc[0]
                # List-index errors (int loc) can't be handled here.
                if not isinstance(fname, str):
                    continue
                if fname in required:
                    log.warning(
                        "Required field '%s' failed in %s: %s",
                        fname,
                        model_cls.__name__,
                        err.get("msg", ""),
                    )
                    return None
                if fname in cleaned:
                    log.debug(
                        "Dropping field '%s' from %s: %s",
                        fname,
                        model_cls.__name__,
                        err.get("msg", ""),
                    )
                    del cleaned[fname]
                    dropped = True
            if not dropped:
                log.warning(
                    "Could not construct %s: no droppable field found",
                    model_cls.__name__,
                )
                return None

    return None
