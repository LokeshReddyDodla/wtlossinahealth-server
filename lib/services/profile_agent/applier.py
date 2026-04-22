"""Apply a validated draft to the database in one transaction.

Mutators are registered per *entity* (not per field). Within an entity,
creating vs updating is symmetric: fetch-or-construct, setattr the
coerced values, the ORM cascade handles the rest.

Cardinality dispatch:
  * `one`        — 1:1 scalar entity; create-or-update the single row
  * `many_flat`  — 1:N of string-valued rows; list fully replaced

The caller is responsible for validation + coercion before entering here.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from lib.models.patient_alcohol_consumption import PatientAlcoholConsumption
from lib.models.patient_daily_activity import PatientDailyActivity
from lib.models.patient_diabetic_history import PatientDiabeticHistory
from lib.models.patient_drug_allergy import PatientDrugAllergy
from lib.models.patient_eating_habit import PatientEatingHabit
from lib.models.patient_family_diabetic_history import PatientFamilyDiabeticHistory
from lib.models.patient_food_allergy import PatientFoodAllergy
from lib.models.patient_medical_history import PatientMedicalHistory
from lib.models.patient_sleep_habit import PatientSleepHabit
from lib.models.patient_smoking_habit import PatientSmokingHabit
from lib.services.profile_agent.config import (
    FIELD_TO_ENTITY,
    SECTIONS,
    EntityConfig,
)

logger = logging.getLogger(__name__)


_ORM_MODEL_BY_NAME = {
    "PatientDailyActivity": PatientDailyActivity,
    "PatientAlcoholConsumption": PatientAlcoholConsumption,
    "PatientSmokingHabit": PatientSmokingHabit,
    "PatientEatingHabit": PatientEatingHabit,
    "PatientSleepHabit": PatientSleepHabit,
    "PatientDiabeticHistory": PatientDiabeticHistory,
    "PatientFamilyDiabeticHistory": PatientFamilyDiabeticHistory,
    "PatientMedicalHistory": PatientMedicalHistory,
    "PatientDrugAllergy": PatientDrugAllergy,
    "PatientFoodAllergy": PatientFoodAllergy,
}


def apply_coerced_changes(patient, coerced_changes: Dict[str, Any]) -> None:
    """Group changes by entity and dispatch to the right mutator.

    Mutates `patient` in place — does not commit. Caller owns transaction.
    """
    # 1. Group by entity.
    grouped: Dict[str, Dict[str, Any]] = {}
    for field_key, value in coerced_changes.items():
        entity = FIELD_TO_ENTITY.get(field_key)
        if entity is None:
            logger.warning("skipping unknown field during apply: %s", field_key)
            continue
        grouped.setdefault(entity["key"], {})[field_key] = value

    # 2. Dispatch per entity.
    for entity_key, entity_changes in grouped.items():
        entity = _lookup_entity(entity_key)
        cardinality = entity.get("cardinality")
        if cardinality == "one":
            _mutate_one(patient, entity, entity_changes)
        elif cardinality == "many_flat":
            _mutate_many_flat(patient, entity, entity_changes)
        else:
            logger.error("unsupported cardinality for entity %s: %s", entity_key, cardinality)


def _lookup_entity(entity_key: str) -> EntityConfig:
    for section in SECTIONS:
        for entity in section["entities"]:
            if entity["key"] == entity_key:
                return entity
    raise KeyError(entity_key)


def _mutate_one(patient, entity: EntityConfig, changes: Dict[str, Any]) -> None:
    orm_attr = entity.get("orm_attr")

    if orm_attr is None:
        # Fields live on Patient itself.
        for field_key, value in changes.items():
            setattr(patient, field_key, value)
        return

    related = getattr(patient, orm_attr, None)
    if related is None:
        model_cls = _ORM_MODEL_BY_NAME[entity["orm_model"]]
        kwargs: Dict[str, Any] = {"patient_id": patient.patient_id}
        kwargs.update(entity.get("construct_defaults", {}))
        kwargs.update(changes)
        related = model_cls(**kwargs)
        setattr(patient, orm_attr, related)
        return

    for field_key, value in changes.items():
        setattr(related, field_key, value)


def _mutate_many_flat(patient, entity: EntityConfig, changes: Dict[str, Any]) -> None:
    """Full-replace the child list using the single list-typed field."""
    orm_attr = entity["orm_attr"]
    model_cls = _ORM_MODEL_BY_NAME[entity["orm_model"]]
    row_col = entity["row_value_column"]
    row_defaults = entity.get("row_defaults", {})

    # The entity has exactly one `list_of_string` field (by config convention).
    # Pull its value — any of the field keys in `changes` can carry it since
    # there's only ever one.
    value = next(iter(changes.values()))
    if not isinstance(value, list):
        raise ValueError(f"many_flat entity {entity['key']} requires a list value")

    new_rows = [
        model_cls(**{"patient_id": patient.patient_id, row_col: item, **row_defaults})
        for item in value
    ]
    setattr(patient, orm_attr, new_rows)
