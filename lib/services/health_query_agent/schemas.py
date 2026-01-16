"""
Pydantic models and schemas for the health query agent.
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional, Annotated, TypedDict

from pydantic import BaseModel, Field


class HealthDataType(str, Enum):
    """Canonical health data types enum."""
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
    SMBG = "smbg"
    MEAL = "meal"
    FITNESS_OVERVIEW = "fitness_overview"
    FITNESS_DIST = "fitness_activity_distribution"
    FITNESS_INACTIVE = "fitness_inactive_periods"
    PROFILE = "profile"
    DOCUMENTS = "patient_document"


class SuggestedAction(BaseModel):
    """Suggested action/question for the user."""
    label: str = Field(..., description="Short button text, e.g., 'Analyze Meals'")
    description: str = Field(
        ...,
        description=(
            "A complete natural language question the user might ask next. "
            "Examples: 'What are my glucose levels for today?', "
            "'Show me my fitness metrics from this week'"
        ),
    )


class DateRange(BaseModel):
    """Date range with inclusive start and exclusive end."""
    start: datetime = Field(description="Inclusive start of date range.")
    end: datetime = Field(description="Exclusive end of date range.")


class TimeRange(BaseModel):
    """Time of day range for filtering."""
    start_hour: Optional[int] = Field(None, description="Start hour (0-23), inclusive.")
    end_hour: Optional[int] = Field(None, description="End hour (0-23), exclusive.")


class QueryIntent(BaseModel):
    """Parsed query intent with all extracted information."""
    is_ready: bool = Field(
        ..., description="True if we have enough info (Type + Date) to query."
    )
    data_types: List[HealthDataType] = Field(
        default=[],
        description="Mapped canonical types from the HealthDataType enum.",
    )
    date_range: Optional[DateRange] = Field(
        None, description="The calculated main date range for the query."
    )
    hour_range: Optional[TimeRange] = Field(
        None, description="The calculated main hour range for the query."
    )
    month_filters: Optional[List[int]] = Field(
        None,
        description="List of month numbers (1-12) mentioned in the query.",
    )
    time_buckets: List[str] = Field(
        default_factory=list,
        description="Time of day buckets (morning, afternoon, evening, night).",
    )
    clarification_msg: Optional[str] = Field(
        None,
        description="Friendly conversational message when is_ready is False.",
    )
    suggestions: List[SuggestedAction] = Field(
        default=[], description="Suggested next steps."
    )
    confidence: Optional[float] = Field(
        None,
        description="Confidence score (0.0-1.0) for intent extraction, for debugging.",
    )


class AgentState(TypedDict):
    """State definition for the LangGraph agent."""
    messages: Annotated[List[dict], "Conversation history"]
    intent: Optional[QueryIntent]
    final_response: Optional[str]
    search_confidence: Optional[float]  # Top search result similarity score
    patient_ids: Optional[List[str]]  # Patient IDs for filtering


class QueryResponse(BaseModel):
    """Response model for query processing."""
    type: str = "response"
    is_ready: bool
    user_message: str
    message_count: int
    turn_number: int
    message: str
    data_types: Optional[List[str]] = None
    date_range: Optional[dict] = None
    hour_range: Optional[dict] = None
    month_filters: Optional[List[int]] = None
    time_buckets: Optional[List[str]] = None
    final_response: Optional[str] = None
    clarification_msg: Optional[str] = None
    suggestions: Optional[List[dict]] = None
    confidence: Optional[float] = Field(
        None, description="Intent extraction confidence score (0.0-1.0), for debugging."
    )
    search_confidence: Optional[float] = Field(
        None, description="Top search result similarity score (0.0-1.0), for debugging."
    )