"""Schemas for the Profile Update micro-agent.

Implements a **draft-change-set** workflow: changes accumulate in a draft
and are only written to the database after the user gives final confirmation.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ── Updatable fields ────────────────────────────────────────────────────────
class UpdatableField(str, Enum):
    """Profile fields the agent is allowed to update.

    Values must match the column names on the Patient model (for basic fields)
    or well-known keys that the service maps to the correct child model
    (for lifestyle / medical-history fields).
    """

    # ── Basic (Patient table columns) ───────────────────────────────────────
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    EMAIL = "email"
    DOB = "dob"
    GENDER = "gender"
    HEIGHT = "height"
    WEIGHT = "weight"
    WAIST = "waist"
    PROFILE_PICTURE = "profile_picture"
    LOCALE = "locale"

    # ── Lifestyle (child models) ────────────────────────────────────────────
    ACTIVITY_LEVEL = "activity_level"
    CONSUME_ALCOHOL = "consume_alcohol"
    SMOKE_STATUS = "smoke_status"
    SLEEP_QUALITY = "sleep_quality"
    MEALS_PER_DAY = "meals_per_day"
    SNACKS_COUNT = "snacks_count"

    # ── Allergies ───────────────────────────────────────────────────────────
    FOOD_ALLERGIES = "food_allergies"
    DRUG_ALLERGIES = "drug_allergies"

    # ── Medical history ─────────────────────────────────────────────────────
    TYPE_OF_DIABETES = "type_of_diabetes"
    HAS_MEDICATION = "has_medication"
    MEDICAL_CONDITIONS = "medical_conditions"

    # ── Helpers ─────────────────────────────────────────────────────────────
    @classmethod
    def human_labels(cls) -> Dict[str, str]:
        """Return a mapping from enum value → human-friendly label."""
        return {
            # Basic
            cls.FIRST_NAME.value: "First Name",
            cls.LAST_NAME.value: "Last Name",
            cls.EMAIL.value: "Email",
            cls.DOB.value: "Date of Birth",
            cls.GENDER.value: "Gender",
            cls.HEIGHT.value: "Height (cm)",
            cls.WEIGHT.value: "Weight (kg)",
            cls.WAIST.value: "Waist (cm)",
            cls.PROFILE_PICTURE.value: "Profile Picture URL",
            cls.LOCALE.value: "Locale / Language",
            # Lifestyle
            cls.ACTIVITY_LEVEL.value: "Activity Level",
            cls.CONSUME_ALCOHOL.value: "Alcohol Consumption (yes/no)",
            cls.SMOKE_STATUS.value: "Smoking Status (yes/no)",
            cls.SLEEP_QUALITY.value: "Sleep Quality",
            cls.MEALS_PER_DAY.value: "Meals Per Day",
            cls.SNACKS_COUNT.value: "Snacks Per Day",
            # Allergies
            cls.FOOD_ALLERGIES.value: "Food Allergies",
            cls.DRUG_ALLERGIES.value: "Drug Allergies",
            # Medical history
            cls.TYPE_OF_DIABETES.value: "Type of Diabetes",
            cls.HAS_MEDICATION.value: "Currently on Medication (yes/no)",
            cls.MEDICAL_CONDITIONS.value: "Medical Conditions",
        }

    @classmethod
    def list_for_prompt(cls) -> str:
        """List of fields with their snake_case keys for the LLM prompt."""
        labels = cls.human_labels()
        lines = [f"- {key} ({label})" for key, label in labels.items()]
        return "\n".join(lines)


# ── Field → profile_completion section mapping ──────────────────────────────
FIELD_TO_SECTION: Dict[str, str] = {
    # Basic
    UpdatableField.FIRST_NAME.value: "basic",
    UpdatableField.LAST_NAME.value: "basic",
    UpdatableField.EMAIL.value: "basic",
    UpdatableField.DOB.value: "basic",
    UpdatableField.GENDER.value: "basic",
    UpdatableField.HEIGHT.value: "basic",
    UpdatableField.WEIGHT.value: "basic",
    UpdatableField.WAIST.value: "basic",
    UpdatableField.PROFILE_PICTURE.value: "basic",
    UpdatableField.LOCALE.value: "basic",
    # Lifestyle
    UpdatableField.ACTIVITY_LEVEL.value: "lifestyle",
    UpdatableField.CONSUME_ALCOHOL.value: "lifestyle",
    UpdatableField.SMOKE_STATUS.value: "lifestyle",
    UpdatableField.SLEEP_QUALITY.value: "lifestyle",
    UpdatableField.MEALS_PER_DAY.value: "lifestyle",
    UpdatableField.SNACKS_COUNT.value: "lifestyle",
    UpdatableField.FOOD_ALLERGIES.value: "lifestyle",
    # Medical history
    UpdatableField.DRUG_ALLERGIES.value: "medical_history",
    UpdatableField.TYPE_OF_DIABETES.value: "medical_history",
    UpdatableField.HAS_MEDICATION.value: "medical_history",
    UpdatableField.MEDICAL_CONDITIONS.value: "medical_history",
}

# Fields that live directly on the Patient table (basic section).
BASIC_FIELDS: set[str] = {
    f.value for f in UpdatableField
    if FIELD_TO_SECTION.get(f.value) == "basic"
}

# Fields that map to lifestyle child models.
LIFESTYLE_FIELDS: set[str] = {
    f.value for f in UpdatableField
    if FIELD_TO_SECTION.get(f.value) == "lifestyle"
}

# Fields that map to medical-history child models.
MEDICAL_HISTORY_FIELDS: set[str] = {
    f.value for f in UpdatableField
    if FIELD_TO_SECTION.get(f.value) == "medical_history"
}


# ── Draft state (persisted in Mongo) ────────────────────────────────────────
class DraftState(str, Enum):
    """Lifecycle states for a profile-update draft."""

    COLLECTING = "collecting"
    REVIEWING = "reviewing"
    APPLYING = "applying"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# ── LLM structured-output types ─────────────────────────────────────────────

# Action types the LLM may emit.
ActionType = Literal["set", "remove", "show_draft", "confirm_all", "cancel_all", "query"]


class LLMAction(BaseModel):
    """A single intent-action extracted by the LLM."""

    action: ActionType
    field: Optional[str] = None
    value: Optional[str] = None


class LLMResponse(BaseModel):
    """Structured output expected from the LLM."""

    actions: List[LLMAction] = Field(default_factory=list)
    reply: str = ""


# ── API request / response ──────────────────────────────────────────────────
class ProfileUpdateChatRequest(BaseModel):
    """Payload sent by the client for each chat turn.

    No ``conversation_id`` — the active draft is resolved automatically
    from the authenticated ``patient_id``.
    """

    message: str = Field(..., min_length=1, max_length=2000)


class ProfileUpdateChatResponse(BaseModel):
    """Data returned to the client after each chat turn."""

    reply: str
    state: str = Field(
        description="Current draft state for client-side UX hints."
    )
    draft_changes: Optional[Dict[str, str]] = Field(
        None,
        description="Current pending draft changes (field → raw value).",
    )
    applied_changes: Optional[Dict[str, str]] = Field(
        None,
        description="Fields actually written to DB. Only set when state=completed.",
    )


class DraftSummaryResponse(BaseModel):
    """Summary of a patient's active draft, used by GET /draft."""

    state: str
    draft_changes: Dict[str, str] = Field(default_factory=dict)
    message_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── Mongo document shape (for type-safety, not enforced at DB level) ────────
class DraftDocument(BaseModel):
    """Shape of documents in the ``profile_update_conversations`` collection.

    One *active* document per patient.  Completed / cancelled drafts have
    ``status`` set to ``"completed"`` / ``"cancelled"`` and are kept for
    history.
    """

    patient_id: str
    status: str = "active"  # "active" | "completed" | "cancelled"
    state: str = DraftState.COLLECTING.value
    draft_changes: Dict[str, str] = Field(default_factory=dict)
    messages: List[Dict[str, str]] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None