from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Annotated, List, Optional, TypedDict

from pydantic import BaseModel, Field

from lib.services.health_query_agent.state_constants import RESET

if TYPE_CHECKING:
    from .contracts import QueryIntent


class HealthDataType(str, Enum):
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
    def _missing_(cls, value):
        if isinstance(value, str):
            return cls.__members__.get(value.upper())


def messages_reducer(old: list | None, new: Any):
    if new == RESET:
        return []

    if old is None:
        old = []

    if isinstance(new, list):
        return old + new

    raise ValueError(f"Invalid messages update: {new}")


class AgentState(TypedDict):
    messages: Annotated[list[dict], messages_reducer]
    intent: "QueryIntent"
    final_response: Optional[str]
    search_confidence: Optional[float]
    patient_ids: Optional[List[str]]
    user_role: Optional[str]
    conversation_context: Optional[dict]
    patient_memory_facts: Optional[List[dict]]
    thread_state: Optional[dict]
    intent_plan: Optional[dict]
    retrieval_plan: Optional[dict]
    analysis_snapshot: Optional[dict]
    executed_tools: Optional[List[str]]
    retrieval_metrics: Optional[dict]


class SuggestedAction(BaseModel):
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
    start: datetime = Field(description="Inclusive start of date range.")
    end: datetime = Field(description="Exclusive end of date range.")


class TimeRange(BaseModel):
    start_hour: Optional[int] = Field(None, description="Start hour (0-23), inclusive.")
    end_hour: Optional[int] = Field(None, description="End hour (0-23), exclusive.")


class NumericRange(BaseModel):
    gte: Optional[float] = None
    lte: Optional[float] = None
    gt: Optional[float] = None
    lt: Optional[float] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.model_dump(exclude_none=True).items()}


class NumericFilter(BaseModel):
    key: str = Field(description="Exact Qdrant payload key.")
    range_condition: NumericRange


class QueryIntent(BaseModel):
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
    numeric_filters: List[NumericFilter] = Field(
        default_factory=list,
        description="All metric constraints mapped to their exact Qdrant key and range condition (e.g., glucose > 200).",
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


class QueryResponse(BaseModel):
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
    numeric_filters: Optional[List[NumericFilter]] = None
    final_response: Optional[str] = None
    clarification_msg: Optional[str] = None
    suggestions: Optional[List[dict]] = None
    confidence: Optional[float] = Field(
        None, description="Intent extraction confidence score (0.0-1.0), for debugging."
    )
    search_confidence: Optional[float] = Field(
        None, description="Top search result similarity score (0.0-1.0), for debugging."
    )


class ConversationMessage(BaseModel):
    message_type: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(..., description="Message timestamp")
    intent: Optional[dict] = Field(
        None, description="Intent data (for assistant messages)"
    )
    response: Optional[dict] = Field(
        None, description="Response data (for assistant messages)"
    )
    metadata: Optional[dict] = Field(None, description="Additional metadata")


class ConversationHistoryResponse(BaseModel):
    user_id: str = Field(..., description="User ID")
    total_messages: int = Field(..., description="Total number of messages")
    messages: list[ConversationMessage] = Field(..., description="List of messages")


__all__ = [
    "HealthDataType",
    "AgentState",
    "messages_reducer",
    "SuggestedAction",
    "DateRange",
    "TimeRange",
    "NumericRange",
    "NumericFilter",
    "QueryIntent",
    "QueryResponse",
    "ConversationMessage",
    "ConversationHistoryResponse",
]
