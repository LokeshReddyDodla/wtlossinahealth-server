"""Gate evaluation shared by gap_detector and completion.

A gate is a list of conditions (ANDed). Each condition references a
sibling field (default entity = same entity as the gated field, or a
different one if `entity:` is set). Unsatisfied gate = skip the field.
"""

from __future__ import annotations

from typing import Any, Protocol

from lib.services.profile_agent.config import EntityConfig, FieldConfig, entity_by_key


class _ValueView(Protocol):
    """Abstraction over wherever current values live (ORM, dict, draft)."""

    def get(self, field_key: str, entity: EntityConfig) -> Any: ...


def gate_satisfied(
    field: FieldConfig,
    entity: EntityConfig,
    patient_view: _ValueView,
) -> bool:
    """True if the field's gate conditions are all satisfied (or no gate)."""
    gate = field.get("gate")
    if not gate:
        return True

    for cond in gate:
        target_entity_key = cond.get("entity") or entity["key"]
        target_entity = (
            entity if target_entity_key == entity["key"]
            else entity_by_key(target_entity_key)
        )
        actual = patient_view.get(cond["field"], target_entity)

        if cond.get("and_present") and _is_empty(actual):
            return False

        if "equals" in cond:
            if not _values_equal(actual, cond["equals"]):
                return False
        if "not_equals" in cond:
            if _values_equal(actual, cond["not_equals"]):
                return False

    return True


def field_value_from_patient(field_key: str, entity: EntityConfig, patient) -> Any:
    """Read the current value of a field from a SQLAlchemy Patient instance."""
    orm_attr = entity.get("orm_attr")

    if entity.get("cardinality") == "many_flat":
        # Read list of row-values off the relationship.
        rows = getattr(patient, orm_attr, None) or []
        col = entity["row_value_column"]
        return [getattr(r, col) for r in rows]

    if orm_attr is None:
        # Field lives directly on Patient.
        return getattr(patient, field_key, None)

    related = getattr(patient, orm_attr, None)
    if related is None:
        return None
    return getattr(related, field_key, None)


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def _values_equal(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    return str(a).strip().lower() == str(b).strip().lower()
