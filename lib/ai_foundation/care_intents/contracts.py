"""Care Intent contracts — typed shapes for provider-authored guidance.

A care intent is ONE provider instruction for ONE patient ("keep reminding
him to walk after dinner"). Providers type a sentence; the structurer LLM
fills every field, the provider confirms. All enums live here so the API
edge, the structurer, and storage validate against a single source.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    REMIND = "remind"          # nudge the patient toward a behavior
    WATCH = "watch"            # observe a metric/pattern, no nudging
    ENCOURAGE = "encourage"    # reinforce something going well
    RESTRICT = "restrict"      # something to avoid (food, timing, habit)
    ESCALATE = "escalate"      # inform the care team when a condition repeats


class IntentDomain(str, Enum):
    GLUCOSE = "glucose"
    NUTRITION = "nutrition"
    FITNESS = "fitness"
    SLEEP = "sleep"
    MEDICATION = "medication"
    WEIGHT = "weight"
    VITALS = "vitals"
    GENERAL = "general"


class IntentCadence(str, Enum):
    DAILY = "daily"      # worth a nudge on days the behavior is missing
    EVENT = "event"      # reacts to a data event (meal logged, threshold)
    PASSIVE = "passive"  # context only — colors replies, never initiates


DEFAULT_REVIEW_DAYS = 14


class StructuredCareIntent(BaseModel):
    """What the structurer LLM extracts from the provider's sentence."""

    intent_type: IntentType
    domain: IntentDomain
    trigger_condition: str | None = Field(
        default=None,
        description=(
            "Human-readable condition for when this intent is relevant, e.g. "
            "'no walk logged within 2h after dinner'. null for passive intents."
        ),
    )
    cadence: IntentCadence
    patient_summary: str = Field(
        description=(
            "One friendly sentence the PATIENT will see describing this focus "
            "area — warm, plain English, no clinical jargon."
        ),
    )
    success_criteria: str | None = Field(
        default=None,
        description="Measurable bar if the provider implied one, e.g. 'walked 5 of 7 days'.",
    )
    review_days: int = Field(
        default=DEFAULT_REVIEW_DAYS,
        ge=1,
        le=90,
        description="Days until the provider should review this intent.",
    )
    # Safety gate — nudges must never carry clinical orders.
    safety_flag: bool = Field(
        default=False,
        description=(
            "true if the instruction changes medication dosing, starts/stops a "
            "drug, gives a diagnosis, or belongs in a prescription rather than "
            "a lifestyle nudge."
        ),
    )
    safety_reason: str | None = Field(
        default=None,
        description="Why it was flagged — shown to the provider.",
    )


class CareIntentView(BaseModel):
    """API shape for a stored intent (provider and patient surfaces)."""

    care_intent_id: str
    patient_id: str
    author_id: str
    author_role: str
    author_name: str
    original_text: str
    intent_type: IntentType
    domain: IntentDomain
    trigger_condition: str | None = None
    cadence: IntentCadence
    patient_summary: str
    success_criteria: str | None = None
    review_date: date
    status: str
    created_at: str
