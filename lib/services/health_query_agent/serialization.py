"""
Serialization utilities for converting complex objects to JSON-serializable structures.
"""
from dataclasses import asdict, is_dataclass
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

    if is_dataclass(value) and not isinstance(value, type):
        return to_checkpoint_safe(asdict(value))

    if hasattr(value, "model_dump") and callable(value.model_dump):
        return to_checkpoint_safe(value.model_dump())

    if hasattr(value, "dict") and callable(value.dict):
        return to_checkpoint_safe(value.dict())

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

    if hasattr(value, "__dict__") and not isinstance(value, type):
        return to_checkpoint_safe(
            {
                key: attr
                for key, attr in vars(value).items()
                if not key.startswith("_") and not callable(attr)
            }
        )

    return value
