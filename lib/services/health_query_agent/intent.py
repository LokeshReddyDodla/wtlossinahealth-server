from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from .types import HealthDataType


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
