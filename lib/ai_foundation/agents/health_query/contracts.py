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
        description=(
            "Durable facts about the patient mentioned in the message. "
            "Each item: {\"key\": str, \"value\": str}. "
            "Examples: {\"key\": \"goal\", \"value\": \"fat loss\"}, "
            "{\"key\": \"dietary_preference\", \"value\": \"vegetarian\"}, "
            "{\"key\": \"body_note\", \"value\": \"has increased muscle mass\"}, "
            "{\"key\": \"fasting_context\", \"value\": \"intermittent fasting 16:8\"}. "
            "Only extract facts the user explicitly states. Do NOT infer."
        ),
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
