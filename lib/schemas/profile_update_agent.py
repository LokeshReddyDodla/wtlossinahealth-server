"""Schemas for the Profile Update micro-agent."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Updatable fields ────────────────────────────────────────────────────────
class UpdatableField(str, Enum):
    """Profile fields the agent is allowed to update.

    Values must match the column names on the Patient model / PatientUpdate
    schema so they can be forwarded directly to
    ``PatientProfileService.update_basic_patient_profile``.
    """

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

    @classmethod
    def human_labels(cls) -> Dict[str, str]:
        """Return a mapping from enum value → human-friendly label."""
        return {
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
        }

    @classmethod
    def list_for_prompt(cls) -> str:
        """Comma-separated list suitable for inclusion in an LLM prompt."""
        return ", ".join(cls.human_labels().values())


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
