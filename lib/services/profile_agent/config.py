"""Single authoritative config for the Profile Agent.

This is the ONLY file that needs to change when a new profile field is
added — everything else (gap detection, LLM prompting, validation,
application) is driven from this structure.

## Shape

A list of sections, each with entities, each with fields. A "field" is
the unit the LLM/user interact with. An "entity" is the ORM aggregate
that owns the field (the Patient row itself, or a related table).

## Types

  string | int | float | bool | date | time | enum | list_of_string

## Cardinality

  one              — 1:1 scalar entity (e.g. smoking_habit, diabetic_history)
  many_flat        — 1:N of single-value rows; full-replace on write
                     (e.g. drug_allergies, food_allergies)
                     v1 also uses this for `medical_histories` /
                     `family_diabetic_histories` in degraded mode — see
                     plan notes.

## Gates

Each field may carry `gate: list[condition]`. All conditions are ANDed.
Each condition is one of:

  {"field": <sibling_key>, "equals": <value>}
  {"field": <sibling_key>, "not_equals": <value>}
  {"field": <sibling_key>, "entity": <other_entity_key>, "equals": <value>}

Optional `and_present: True` requires the gate field itself to have a
non-empty value before the gate can evaluate to true.

Fields with unsatisfied gates are:
  * not proactively asked about
  * not counted in required_total for completeness
  * NOT blocked from being set if the LLM emits one (the gate shapes
    the agent's questioning, not what the user is allowed to answer).
"""

from __future__ import annotations

from typing import Any, Dict, List, TypedDict


class GateCondition(TypedDict, total=False):
    field: str
    equals: Any
    not_equals: Any
    entity: str
    and_present: bool


class FieldConfig(TypedDict, total=False):
    key: str
    label: str
    type: str                       # string|int|float|bool|date|time|enum|list_of_string
    required: bool
    values: List[Any]               # for enum
    range: List[float]              # [min, max] for int/float
    gate: List[GateCondition]
    user_provided_value: bool       # hallucination guard: value must appear in user msgs
    prompt: str                     # optional override for proactive questioning


class EntityConfig(TypedDict, total=False):
    key: str                        # logical name, used as dispatch key in applier
    cardinality: str                # one | many_flat
    orm_attr: str                   # relationship name on Patient (or None for patient itself)
    orm_model: str                  # class name for import resolution
    construct_defaults: Dict[str, Any]
    row_value_column: str           # for many_flat: column name holding the string value
    row_defaults: Dict[str, Any]    # for many_flat with extra non-null columns
    fields: List[FieldConfig]


class SectionConfig(TypedDict):
    key: str                        # matches profile_completion section keys
    label: str
    entities: List[EntityConfig]


SECTIONS: List[SectionConfig] = [
    # ─────────────────────────────────────────────────────────────────
    # BASIC — lives on the Patient row directly
    # ─────────────────────────────────────────────────────────────────
    {
        "key": "basic",
        "label": "Basic Info",
        "entities": [
            {
                "key": "patient",
                "cardinality": "one",
                "orm_attr": None,  # fields live on patient itself
                "orm_model": "Patient",
                "fields": [
                    {
                        "key": "first_name", "label": "First Name",
                        "type": "string", "required": True,
                        "user_provided_value": True,
                    },
                    {
                        "key": "last_name", "label": "Last Name",
                        "type": "string", "required": True,
                        "user_provided_value": True,
                    },
                    {
                        "key": "dob", "label": "Date of Birth",
                        "type": "date", "required": True,
                    },
                    {
                        "key": "gender", "label": "Gender",
                        "type": "enum",
                        "values": ["male", "female", "other"],
                        "required": True,
                    },
                    {
                        "key": "height", "label": "Height (cm)",
                        "type": "float", "range": [30, 300],
                        "required": True,
                    },
                    {
                        "key": "weight", "label": "Weight (kg)",
                        "type": "float", "range": [1, 500],
                        "required": True,
                    },
                    {
                        "key": "waist", "label": "Waist (cm)",
                        "type": "float", "range": [20, 300],
                        "required": True,
                    },
                    {
                        "key": "email", "label": "Email",
                        "type": "string", "required": True,
                        "user_provided_value": True,
                    },
                    {
                        "key": "locale", "label": "Locale / Timezone",
                        "type": "string", "required": False,
                    },
                    # Deliberately excluded: phone_number (immutable),
                    # is_verified (system-controlled), profile_picture
                    # (uploaded via separate endpoint).
                ],
            },
        ],
    },

    # ─────────────────────────────────────────────────────────────────
    # LIFESTYLE
    # ─────────────────────────────────────────────────────────────────
    {
        "key": "lifestyle",
        "label": "Lifestyle",
        "entities": [
            {
                "key": "daily_activity",
                "cardinality": "one",
                "orm_attr": "daily_activity",
                "orm_model": "PatientDailyActivity",
                "fields": [
                    {
                        "key": "activity_level", "label": "Activity Level",
                        "type": "enum",
                        "values": ["sedentary", "light", "moderate", "active", "very_active"],
                        "required": True,
                    },
                ],
            },
            {
                "key": "alcohol_consumption",
                "cardinality": "one",
                "orm_attr": "alcohol_consumption",
                "orm_model": "PatientAlcoholConsumption",
                "construct_defaults": {"consume_alcohol": False},
                "fields": [
                    {
                        "key": "consume_alcohol", "label": "Alcohol Consumption",
                        "type": "bool", "required": True,
                        "prompt": "Do you consume alcohol? (yes/no)",
                    },
                    {
                        "key": "frequency", "label": "Alcohol Frequency",
                        "type": "enum",
                        "values": ["daily", "weekly", "monthly", "rarely"],
                        "gate": [{"field": "consume_alcohol", "equals": True}],
                    },
                    {
                        "key": "quantity", "label": "Alcohol Quantity",
                        "type": "string",
                        "gate": [{"field": "consume_alcohol", "equals": True}],
                    },
                ],
            },
            {
                "key": "smoking_habit",
                "cardinality": "one",
                "orm_attr": "smoking_habit",
                "orm_model": "PatientSmokingHabit",
                "construct_defaults": {"smoke_status": False},
                "fields": [
                    {
                        "key": "smoke_status", "label": "Smoking Status",
                        "type": "bool", "required": True,
                        "prompt": "Do you currently smoke? (yes/no)",
                    },
                    {
                        "key": "years_of_smoking", "label": "Years Smoking",
                        "type": "int", "range": [0, 100],
                        "gate": [{"field": "smoke_status", "equals": True}],
                    },
                    {
                        "key": "cigarettes_per_day", "label": "Cigarettes per Day",
                        "type": "int", "range": [0, 200],
                        "gate": [{"field": "smoke_status", "equals": True}],
                    },
                    # quit_years_ago intentionally omitted from proactive flow —
                    # schema preserves it for reactive updates later.
                ],
            },
            {
                "key": "eating_habit",
                "cardinality": "one",
                "orm_attr": "eating_habit",
                "orm_model": "PatientEatingHabit",
                "fields": [
                    {
                        "key": "meals_per_day", "label": "Meals per Day",
                        "type": "int", "range": [0, 10],
                        "required": True,
                    },
                    {
                        "key": "snacks_count", "label": "Snacks per Day",
                        "type": "int", "range": [0, 10],
                        "required": True,
                    },
                ],
            },
            {
                "key": "sleep_habit",
                "cardinality": "one",
                "orm_attr": "sleep_habit",
                "orm_model": "PatientSleepHabit",
                "construct_defaults": {
                    "sleep_quality": "average",
                    "wake_up_fresh": False,
                    "drowsy_day": False,
                },
                "fields": [
                    {
                        "key": "sleep_quality", "label": "Sleep Quality",
                        "type": "enum",
                        "values": ["good", "average", "poor"],
                        "required": True,
                    },
                    {
                        "key": "wake_up_fresh", "label": "Wake Up Fresh",
                        "type": "bool", "required": True,
                    },
                    {
                        "key": "drowsy_day", "label": "Drowsy During Day",
                        "type": "bool", "required": True,
                    },
                    {
                        "key": "average_sleep_duration", "label": "Average Sleep Duration",
                        "type": "string", "required": True,
                    },
                ],
            },
        ],
    },

    # ─────────────────────────────────────────────────────────────────
    # MEDICAL HISTORY
    # ─────────────────────────────────────────────────────────────────
    {
        "key": "medical_history",
        "label": "Medical History",
        "entities": [
            {
                "key": "diabetic_history",
                "cardinality": "one",
                "orm_attr": "diabetic_history",
                "orm_model": "PatientDiabeticHistory",
                "fields": [
                    {
                        "key": "type_of_diabetes", "label": "Type of Diabetes",
                        "type": "enum",
                        "values": ["Type 1", "Type 2", "Gestational", "Pre-diabetes", "None"],
                        "required": True,
                    },
                    {
                        "key": "years_with_diabetes", "label": "Years with Diabetes",
                        "type": "int", "range": [0, 100],
                        "gate": [
                            {
                                "field": "type_of_diabetes",
                                "not_equals": "None",
                                "and_present": True,
                            }
                        ],
                    },
                    {
                        "key": "is_pregnant", "label": "Currently Pregnant",
                        "type": "bool",
                        "gate": [
                            {
                                "field": "gender",
                                "entity": "patient",
                                "equals": "female",
                            }
                        ],
                    },
                    {
                        "key": "pregnancy_weeks", "label": "Weeks Pregnant",
                        "type": "int", "range": [0, 45],
                        "gate": [
                            {
                                "field": "gender",
                                "entity": "patient",
                                "equals": "female",
                            },
                            {"field": "is_pregnant", "equals": True},
                        ],
                    },
                ],
            },
            {
                "key": "drug_allergies",
                "cardinality": "many_flat",
                "orm_attr": "drug_allergies",
                "orm_model": "PatientDrugAllergy",
                "row_value_column": "allergy_name",
                "fields": [
                    {
                        "key": "drug_allergies", "label": "Drug Allergies",
                        "type": "list_of_string",
                        "required": False,
                    },
                ],
            },
            {
                "key": "food_allergies",
                "cardinality": "many_flat",
                "orm_attr": "food_allergies",
                "orm_model": "PatientFoodAllergy",
                "row_value_column": "allergy_name",
                "fields": [
                    {
                        "key": "food_allergies", "label": "Food Allergies",
                        "type": "list_of_string",
                        "required": False,
                    },
                ],
            },
            {
                "key": "medical_histories",
                "cardinality": "many_flat",
                "orm_attr": "medical_histories",
                "orm_model": "PatientMedicalHistory",
                "row_value_column": "condition",
                "row_defaults": {"duration_years": 0},
                "fields": [
                    {
                        "key": "medical_conditions", "label": "Medical Conditions",
                        "type": "list_of_string",
                        "required": False,
                    },
                ],
            },
            {
                "key": "family_diabetic_histories",
                "cardinality": "many_flat",
                "orm_attr": "family_diabetic_histories",
                "orm_model": "PatientFamilyDiabeticHistory",
                "row_value_column": "family_member",
                "fields": [
                    {
                        "key": "family_diabetic_members", "label": "Family Members with Diabetes",
                        "type": "list_of_string",
                        "required": False,
                    },
                ],
            },
        ],
    },
]


# ── Derived indexes (computed once at import) ──────────────────────────────

def _build_indexes():
    field_to_entity: Dict[str, EntityConfig] = {}
    field_to_section: Dict[str, str] = {}
    field_to_config: Dict[str, FieldConfig] = {}
    entity_to_section: Dict[str, str] = {}
    for section in SECTIONS:
        for entity in section["entities"]:
            entity_to_section[entity["key"]] = section["key"]
            for field in entity["fields"]:
                field_to_entity[field["key"]] = entity
                field_to_section[field["key"]] = section["key"]
                field_to_config[field["key"]] = field
    return field_to_entity, field_to_section, field_to_config, entity_to_section


FIELD_TO_ENTITY, FIELD_TO_SECTION, FIELD_TO_CONFIG, ENTITY_TO_SECTION = _build_indexes()

ALL_FIELD_KEYS: set[str] = set(FIELD_TO_CONFIG.keys())


def entity_by_key(key: str) -> EntityConfig:
    for section in SECTIONS:
        for entity in section["entities"]:
            if entity["key"] == key:
                return entity
    raise KeyError(f"unknown entity key: {key}")


def fields_with_user_provided_value() -> set[str]:
    return {
        k for k, cfg in FIELD_TO_CONFIG.items()
        if cfg.get("user_provided_value") is True
    }
