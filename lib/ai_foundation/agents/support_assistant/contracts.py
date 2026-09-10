"""Typed contracts for the patient support assistant.

Three things cross the agent boundary:

- ``SupportSnapshot`` — read-only facts about the patient (care team,
  permissions, device sync state, recent uploads) assembled by the service
  layer and rendered into the prompt. The agent never queries data itself.
- ``SupportTriage`` — the single structured LLM output: category, urgency,
  whether a human is needed, a one-line staff summary, and the reply text.
- ``HandlingMode`` — the deterministic policy decision the agent derives
  from the triage. The mode, not the model, decides whether the patient sees
  the model's reply, the hold message, or the emergency message.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SupportCategory(str, Enum):
    """What the patient's message is about. Drives handling and the staff
    queue's triage column. Categories the bot may answer itself are listed
    in ``SELF_SERVE_CATEGORIES``."""

    MEAL_LOGGING = "meal_logging"
    APP_PERMISSIONS = "app_permissions"
    DOCUMENT_UPLOAD = "document_upload"
    CGM_SENSOR = "cgm_sensor"
    CONNECTED_DEVICE = "connected_device"
    FITNESS_SLEEP_SYNC = "fitness_sleep_sync"
    GLUCOSE_MANUAL_ENTRY = "glucose_manual_entry"
    CARE_TEAM_CONTACT = "care_team_contact"
    ACCOUNT_LOGIN = "account_login"
    PROFILE = "profile"
    NOTIFICATIONS = "notifications"
    REPORTS_AND_PLANS = "reports_and_plans"
    PRESCRIPTIONS_MEDICATIONS = "prescriptions_medications"
    AI_CHAT = "ai_chat"
    GAMIFICATION = "gamification"
    GENERAL_FAQ = "general_faq"
    GREETING_OR_THANKS = "greeting_or_thanks"
    # Never self-served: a human must act or decide.
    BILLING_OR_PACKAGE = "billing_or_package"
    CARE_PROVIDER_CHANGE = "care_provider_change"
    DATA_CORRECTION_OR_DELETION = "data_correction_or_deletion"
    BUG_OR_ERROR = "bug_or_error"
    FEATURE_REQUEST = "feature_request"
    COMPLAINT = "complaint"
    # Safety routes.
    MEDICAL_QUESTION = "medical_question"
    EMERGENCY = "emergency"
    UNKNOWN = "unknown"


SELF_SERVE_CATEGORIES: frozenset[SupportCategory] = frozenset(
    {
        SupportCategory.MEAL_LOGGING,
        SupportCategory.APP_PERMISSIONS,
        SupportCategory.DOCUMENT_UPLOAD,
        SupportCategory.CGM_SENSOR,
        SupportCategory.CONNECTED_DEVICE,
        SupportCategory.FITNESS_SLEEP_SYNC,
        SupportCategory.GLUCOSE_MANUAL_ENTRY,
        SupportCategory.CARE_TEAM_CONTACT,
        SupportCategory.ACCOUNT_LOGIN,
        SupportCategory.PROFILE,
        SupportCategory.NOTIFICATIONS,
        SupportCategory.REPORTS_AND_PLANS,
        SupportCategory.PRESCRIPTIONS_MEDICATIONS,
        SupportCategory.AI_CHAT,
        SupportCategory.GAMIFICATION,
        SupportCategory.GENERAL_FAQ,
        SupportCategory.GREETING_OR_THANKS,
    }
)


class SupportUrgency(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class HandlingMode(str, Enum):
    """Deterministic outcome of applying policy to a triage."""

    ANSWERED = "answered"                # model reply sent as-is
    HELD_FOR_HUMAN = "held_for_human"    # short ack + standard hold message
    REDIRECTED_MEDICAL = "redirected_medical"  # care-team redirect appended
    EMERGENCY = "emergency"              # emergency template, model reply dropped


class SupportTriage(BaseModel):
    """The one structured output the model produces per patient message."""

    category: SupportCategory = Field(
        description="Single best category for the patient's latest message."
    )
    urgency: SupportUrgency = Field(
        description=(
            "urgent = safety risk or patient cannot use a critical feature at all; "
            "high = blocked on something time-sensitive (sensor down, can't log in); "
            "normal = ordinary question; low = greeting, thanks, curiosity."
        )
    )
    needs_human: bool = Field(
        description=(
            "True when a person must act or decide (billing, provider change, data "
            "changes, bugs, complaints, anything not covered by the knowledge base, "
            "or the patient explicitly asks for a person). False when the reply "
            "fully resolves the question from the knowledge base or snapshot."
        )
    )
    summary: str = Field(
        max_length=240,
        description=(
            "One line for the support staff, in English: what the patient needs and "
            "what has already been told to them. Never include the reply text."
        ),
    )
    reply: str = Field(
        description=(
            "The message to send to the patient, in the patient's language. Warm, "
            "specific, step-by-step where useful. Empty string only for emergencies."
        )
    )


class CareTeamContact(BaseModel):
    name: str
    role: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: bool = True


class FacilityContact(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    emergency_phone: Optional[str] = None
    operating_hours: Optional[str] = None


class PermissionState(BaseModel):
    notifications: Optional[bool] = None
    health: Optional[bool] = None
    camera: Optional[bool] = None
    gallery: Optional[bool] = None
    storage: Optional[bool] = None
    synced_at: Optional[datetime] = None


class DeviceSyncState(BaseModel):
    """One connected glucose source (LibreView export or Sinocare)."""

    provider: str
    sync_status: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    last_reading_at: Optional[datetime] = None
    live_polling_enabled: Optional[bool] = None
    live_last_sync_at: Optional[datetime] = None


class RecentDocument(BaseModel):
    file_name: Optional[str] = None
    category: Optional[str] = None
    uploaded_at: Optional[datetime] = None


class AppDevice(BaseModel):
    platform: Optional[str] = None
    os_version: Optional[str] = None
    app_version: Optional[str] = None
    model: Optional[str] = None
    last_active_at: Optional[datetime] = None


class SupportSnapshot(BaseModel):
    """Read-only patient facts the assistant may cite. Every field is
    optional: a failed lookup leaves it ``None`` and the bot says it could
    not check, rather than the whole reply failing."""

    patient_first_name: Optional[str] = None
    timezone: Optional[str] = None
    language: str = "en"
    facility: Optional[FacilityContact] = None
    care_team: list[CareTeamContact] = Field(default_factory=list)
    active_package_name: Optional[str] = None
    permissions: Optional[PermissionState] = None
    glucose_sources: list[DeviceSyncState] = Field(default_factory=list)
    last_meal_date: Optional[str] = None
    meals_last_7_days: Optional[int] = None
    recent_documents: list[RecentDocument] = Field(default_factory=list)
    device: Optional[AppDevice] = None
    lookup_errors: list[str] = Field(
        default_factory=list,
        description="Names of snapshot sections that could not be loaded.",
    )
