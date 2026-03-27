"""
Health Query Contracts — schemas for intent extraction, response, and
domain classification.

Backward-compatible with the existing QueryResponse API contract so that
clients don't need changes when switching to the foundation agent.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class HealthDataType(str, Enum):
    """Canonical health data types available in the vector store."""

    CGM_RANGE = "cgm_range_stats"
    CGM_SUMMARY = "cgm_summary_stats"
    HYPER_STATS = "hyper_stats"
    HYPO_STATS = "hypo_stats"
    RAPID_SPIKE = "rapid_spike_stats"
    RAPID_DROP = "rapid_drop_stats"
    HYPER_EVENT = "hyper_event"
    HYPO_EVENT = "hypo_event"
    RAPID_SPIKE_EVENT = "rapid_spike_event"
    RAPID_DROP_EVENT = "rapid_drop_event"
    TIME_PERIOD = "time_period_stats"
    AGP = "agp_point"
    CGM_SEMANTIC_WINDOW = "cgm_semantic_window"
    SMBG = "smbg"
    MEAL = "meal"
    FITNESS_OVERVIEW = "fitness_overview"
    FITNESS_DIST = "fitness_activity_distribution"
    FITNESS_INACTIVE = "fitness_inactive_periods"
    VITAL = "vital"
    SLEEP = "sleep"
    PROFILE = "profile"
    DOCUMENTS = "patient_document"

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            return cls.__members__.get(value.upper())
        return None


class DomainName(str, Enum):
    """High-level health domains."""

    MEAL = "meal"
    CGM = "cgm"
    SMBG = "smbg"
    FITNESS = "fitness"
    PROFILE = "profile"
    DOCUMENTS = "documents"
    SLEEP = "sleep"
    VITALS = "vitals"
    PATIENT_SUMMARY = "patient_summary"


# Human-readable domain list for prompts — derived from DomainName enum.
# Excludes internal-only domains (profile, patient_summary).
AVAILABLE_HEALTH_DOMAINS = ", ".join(
    d.value for d in DomainName
    if d not in (DomainName.PROFILE, DomainName.PATIENT_SUMMARY)
)  # → "meal, cgm, smbg, fitness, documents, sleep, vitals"


# Maps each HealthDataType to its parent domain for specialist routing
DOMAIN_MAPPING: dict[DomainName, list[HealthDataType]] = {
    DomainName.CGM: [
        HealthDataType.CGM_RANGE, HealthDataType.CGM_SUMMARY,
        HealthDataType.HYPER_STATS, HealthDataType.HYPO_STATS,
        HealthDataType.RAPID_SPIKE, HealthDataType.RAPID_DROP,
        HealthDataType.HYPER_EVENT, HealthDataType.HYPO_EVENT,
        HealthDataType.RAPID_SPIKE_EVENT, HealthDataType.RAPID_DROP_EVENT,
        HealthDataType.TIME_PERIOD, HealthDataType.AGP,
        HealthDataType.CGM_SEMANTIC_WINDOW,
    ],
    DomainName.MEAL: [HealthDataType.MEAL],
    DomainName.FITNESS: [
        HealthDataType.FITNESS_OVERVIEW,
        HealthDataType.FITNESS_DIST,
        HealthDataType.FITNESS_INACTIVE,
    ],
    DomainName.SMBG: [HealthDataType.SMBG],
    DomainName.VITALS: [HealthDataType.VITAL],
    DomainName.SLEEP: [HealthDataType.SLEEP],
    DomainName.PROFILE: [HealthDataType.PROFILE],
    DomainName.DOCUMENTS: [HealthDataType.DOCUMENTS],
}

# Reverse mapping: HealthDataType → DomainName
_TYPE_TO_DOMAIN: dict[HealthDataType, DomainName] = {}
for _domain, _types in DOMAIN_MAPPING.items():
    for _dt in _types:
        _TYPE_TO_DOMAIN[_dt] = _domain

# Specialist domain names (domains that have specialist agents)
SPECIALIST_DOMAINS = {"glucose", "nutrition", "fitness", "vitals", "sleep", "documents"}

# Map DomainName enum to specialist domain key
_DOMAIN_TO_SPECIALIST: dict[DomainName, str] = {
    DomainName.CGM: "glucose",
    DomainName.SMBG: "glucose",
    DomainName.MEAL: "nutrition",
    DomainName.FITNESS: "fitness",
    DomainName.VITALS: "vitals",
    DomainName.SLEEP: "sleep",
    DomainName.DOCUMENTS: "documents",
}


def resolve_domains(data_types: list[HealthDataType]) -> list[DomainName]:
    """Map data types from intent extraction to unique domains."""
    domains: set[DomainName] = set()
    for dt in data_types:
        domain = _TYPE_TO_DOMAIN.get(dt)
        if domain:
            domains.add(domain)
    return sorted(domains, key=lambda d: d.value)


def resolve_specialist_domains(data_types: list[HealthDataType]) -> list[str]:
    """Map data types to specialist domain keys (glucose, nutrition, fitness)."""
    specialists: set[str] = set()
    for dt in data_types:
        domain = _TYPE_TO_DOMAIN.get(dt)
        if domain:
            specialist = _DOMAIN_TO_SPECIALIST.get(domain)
            if specialist:
                specialists.add(specialist)
    return sorted(specialists)


class ResponseMode(str, Enum):
    """How the agent should format its response."""

    LIST = "list"
    SUMMARIZE = "summarize"
    EVALUATE = "evaluate"
    COMPARE = "compare"
    RECOMMEND = "recommend"
    CLARIFY = "clarify"


# ---------------------------------------------------------------------------
# Intent extraction (LLM-produced)
# ---------------------------------------------------------------------------


class DateRange(BaseModel):
    start: datetime = Field(description="Inclusive start of date range.")
    end: datetime = Field(description="Exclusive end of date range.")


class TimeRange(BaseModel):
    start_hour: int | None = Field(None, description="Start hour (0-23), inclusive.")
    end_hour: int | None = Field(None, description="End hour (0-23), exclusive.")


class NumericRange(BaseModel):
    gte: float | None = None
    lte: float | None = None
    gt: float | None = None
    lt: float | None = None


class NumericFilter(BaseModel):
    key: str = Field(description="Exact Qdrant payload key.")
    range_condition: NumericRange


class SuggestedAction(BaseModel):
    label: str = Field(..., description="Short button text.")
    description: str = Field(..., description="Complete follow-up question.")


class QueryIntent(BaseModel):
    """Structured intent extracted from the user's message by the LLM.

    This is the response_model passed to ModelGateway.extract().
    """

    is_ready: bool = Field(
        ..., description="True if enough info to execute a data query.",
    )
    data_types: list[HealthDataType] = Field(
        default_factory=list,
        description="Canonical data types needed.",
    )
    date_range: DateRange | None = Field(
        None, description="Main date range for the query.",
    )
    hour_range: TimeRange | None = Field(
        None, description="Hour-of-day filter.",
    )
    month_filters: list[int] | None = Field(
        None, description="Month numbers (1-12) if mentioned.",
    )
    time_buckets: list[str] = Field(
        default_factory=list,
        description="Time-of-day buckets: morning, afternoon, evening, night.",
    )
    numeric_filters: list[NumericFilter] = Field(
        default_factory=list,
        description="Numeric constraints (e.g., glucose > 200).",
    )
    clarification_msg: str | None = Field(
        None, description="Friendly message when is_ready is False.",
    )
    suggestions: list[SuggestedAction] = Field(
        default_factory=list,
        description="Suggested follow-up actions.",
    )
    confidence: float | None = Field(
        None, description="Confidence score 0.0-1.0.",
    )
    extracted_facts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Deprecated — facts are now extracted via a separate LLM call.",
    )


class PatientFact(BaseModel):
    """A single extracted patient fact."""

    key: str = Field(
        ...,
        description=(
            "Fact category. Must be one of: goal, weight, dietary_preference, "
            "food_allergy, body_note, medication_note, fasting_context, "
            "communication_style, medical_condition, activity_preference, "
            "or any other descriptive key."
        ),
    )
    value: str = Field(
        ...,
        description="The fact value, exactly as stated by the user.",
    )


class ExtractedFacts(BaseModel):
    """Facts extracted from a user message. Used as response_model for a dedicated LLM call."""

    facts: list[PatientFact] = Field(
        ...,
        description=(
            "ALL durable patient facts found in the message. "
            "Extract every goal, weight, dietary preference, allergy, body note, "
            "medical condition, medication, fasting context mentioned. "
            "Return an empty list ONLY if the message contains NO patient facts."
        ),
    )
    has_facts: bool = Field(
        ...,
        description="True if any patient facts were found in the message. False otherwise.",
    )


# ---------------------------------------------------------------------------
# API Response (backward-compatible)
# ---------------------------------------------------------------------------


class QueryResponse(BaseModel):
    """Response returned to the client. Matches the existing API contract."""

    type: str = "response"
    is_ready: bool
    user_message: str
    message: str
    turn_number: int = 0
    data_types: list[str] | None = None
    date_range: dict | None = None
    hour_range: dict | None = None
    month_filters: list[int] | None = None
    time_buckets: list[str] | None = None
    numeric_filters: list[dict] | None = None
    final_response: str | None = None
    clarification_msg: str | None = None
    suggestions: list[dict] | None = None
    confidence: float | None = None
    search_confidence: float | None = None
    trace_id: str | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
