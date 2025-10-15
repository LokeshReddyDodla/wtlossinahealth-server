from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


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


class DateRange(BaseModel):
    start: datetime = Field(description="Inclusive start of date range.")
    end: datetime = Field(description="Exclusive end of date range.")


class TimeRange(BaseModel):
    start_hour: Optional[int] = None
    end_hour: Optional[int] = None


class SearchIntent(BaseModel):
    data_types: List[str] = Field(
        default_factory=list,
        description="List of exact 'data_type' values (e.g., ['cgm_summary_stats', 'hyper_event']).",
    )

    # sources: List[str] = Field(
    #     default_factory=list,
    #     description="List of data sources referenced in the query (e.g., ['cgm', 'meal', 'fitness', 'sleep', 'smbg']).",
    # )

    date_range: Optional[DateRange] = Field(
        None, description="The calculated main date range for the query."
    )

    hour_range: Optional[TimeRange] = None

    numeric_filters: List[NumericFilter] = Field(
        default_factory=list,
        description="All metric constraints mapped to their exact Qdrant key and range condition (e.g., glucose > 200).",
    )

    semantic_query: Optional[str] = Field(
        None, description="Reformulated query for vector similarity search."
    )

    month_filters: Optional[List[int]] = Field(
        None,
        description="List of month numbers (1-12) mentioned in the query, e.g. [8, 9] for 'August to September'. Use this instead of date_range for month-based comparisons.",
    )

    time_buckets: List[str] = Field(
        default_factory=list,
        description="One or more time_of_day_bucket values (morning, afternoon, evening, night)",
    )

    confidence: float = Field(
        ..., description="Confidence score (0.0–1.0) of interpretation"
    )
