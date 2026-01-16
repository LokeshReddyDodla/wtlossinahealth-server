"""
Serialization utilities for converting complex objects to JSON-serializable structures.
"""
from typing import Any
from datetime import datetime
from enum import Enum

from pydantic import BaseModel as PydanticBaseModel


def to_checkpoint_safe(value: Any) -> Any:
    if isinstance(value, PydanticBaseModel):
        data = (
            value.model_dump(exclude_unset=False, exclude_none=False)
            if hasattr(value, "model_dump")
            else value.dict(exclude_unset=False, exclude_none=False)
        )
        return to_checkpoint_safe(data)

    if isinstance(value, dict):
        return {
            k: to_checkpoint_safe(v)
            for k, v in value.items()
            if not k.startswith("_")
        }

    if isinstance(value, (list, tuple)):
        return [to_checkpoint_safe(v) for v in value]

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, datetime):
        return value.isoformat()

    return value
