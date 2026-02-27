"""Schemas for the Profile Update micro-agent."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional

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
        """Comma-separated list suitable for inclusion in an LLM prompt."""
        return ", ".join(cls.human_labels().values())


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


# ── Conversation state (persisted in Mongo) ─────────────────────────────────
class ConversationState(str, Enum):
    """Finite-state machine states for a profile-update conversation."""

    IDLE = "idle"
    AWAITING_FIELD = "awaiting_field"
    AWAITING_VALUE = "awaiting_value"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"


# ── LLM structured-output schema ────────────────────────────────────────────
class ParsedIntent(BaseModel):
    """What the LLM extracts from the user's message."""

    field: Optional[str] = Field(
        None,
        description="The profile field the user wants to update (snake_case). "
        "Must be one of the UpdatableField values, or null if unclear.",
    )
    value: Optional[str] = Field(
        None,
        description="The new value the user wants to set, or null if not provided.",
    )
    confirmation: Optional[bool] = Field(
        None,
        description="True if the user confirmed the update, False if they declined, null if not applicable.",
    )


# ── API request / response ──────────────────────────────────────────────────
class ProfileUpdateChatRequest(BaseModel):
    """Payload sent by the client for each chat turn."""

    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[str] = Field(
        None,
        description="Existing conversation ID to continue. "
        "Omit or set to null to start a new conversation.",
    )


class ProfileUpdateChatResponse(BaseModel):
    """Data returned to the client after each chat turn."""

    conversation_id: str
    reply: str
    state: str = Field(
        description="Current conversation state for client-side UX hints."
    )
    updated_field: Optional[str] = None
    updated_value: Optional[Any] = None


class ConversationListResponse(BaseModel):
    """Summary of a single conversation, used in the list endpoint."""

    conversation_id: str
    state: str
    target_field: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    message_count: int = 0


# ── Mongo document shape (for type-safety, not enforced at DB level) ────────
class ConversationDocument(BaseModel):
    """Shape of documents in the ``profile_update_conversations`` collection."""

    conversation_id: str
    patient_id: str
    state: str = ConversationState.IDLE.value
    target_field: Optional[str] = None
    target_value: Optional[Any] = None
    messages: List[Dict[str, str]] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
