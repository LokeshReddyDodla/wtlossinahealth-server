"""Startup validator: every config field resolves to a real schema field.

Run once at app boot. Fails loudly if the config references a field that
no longer exists on `CompletePatientProfile` or one of its nested models —
the usual way this breaks is when someone renames a column but forgets
to update the config.
"""

from __future__ import annotations

import logging
from typing import Any, List, get_args, get_origin

from pydantic import BaseModel

from lib.schemas.patient import CompletePatientProfile
from lib.services.profile_agent.config import SECTIONS, EntityConfig

logger = logging.getLogger(__name__)


def _unwrap_model(annotation: Any) -> type[BaseModel] | None:
    """Return the inner Pydantic model if annotation is Optional[Model] or List[Model]."""
    origin = get_origin(annotation)
    if origin is None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return annotation
        return None
    for arg in get_args(annotation):
        if isinstance(arg, type) and issubclass(arg, BaseModel):
            return arg
        inner = _unwrap_model(arg)
        if inner is not None:
            return inner
    return None


def _fields_on_entity(entity: EntityConfig) -> set[str]:
    """Return the set of valid schema field keys for the entity.

    - entity.orm_attr is None  → Patient's own direct fields
    - entity.orm_attr is set   → the nested Pydantic model's fields
    """
    orm_attr = entity.get("orm_attr")
    if orm_attr is None:
        return set(CompletePatientProfile.model_fields.keys())

    model_fields = CompletePatientProfile.model_fields
    if orm_attr not in model_fields:
        return set()

    annotation = model_fields[orm_attr].annotation
    nested_model = _unwrap_model(annotation)
    if nested_model is None:
        return set()
    return set(nested_model.model_fields.keys())


def validate_config_against_schema() -> List[str]:
    """Return a list of error strings. Empty list = all good."""
    errors: List[str] = []

    for section in SECTIONS:
        for entity in section["entities"]:
            # For many_flat list entities, the config field key is a
            # user-facing name (e.g. "medical_conditions") and doesn't
            # map 1:1 to the child model's columns — those are validated
            # via `row_value_column` instead.
            if entity.get("cardinality") == "many_flat":
                orm_attr = entity.get("orm_attr")
                if orm_attr and orm_attr not in CompletePatientProfile.model_fields:
                    errors.append(
                        f"entity '{entity['key']}': orm_attr '{orm_attr}' not on CompletePatientProfile"
                    )
                continue

            valid_fields = _fields_on_entity(entity)
            for field in entity["fields"]:
                if field["key"] not in valid_fields:
                    errors.append(
                        f"section '{section['key']}' / entity '{entity['key']}': "
                        f"field '{field['key']}' not found on schema"
                    )

    return errors


def assert_valid_config() -> None:
    """Raise RuntimeError if config-vs-schema validation fails. Call at boot."""
    errs = validate_config_against_schema()
    if errs:
        msg = "profile_agent config out of sync with CompletePatientProfile:\n" + "\n".join(f"  - {e}" for e in errs)
        logger.error(msg)
        raise RuntimeError(msg)
