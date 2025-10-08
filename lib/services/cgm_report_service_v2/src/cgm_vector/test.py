from datetime import datetime, timezone
from typing import Any, List, Optional, Literal
from enum import Enum
from pydantic import BaseModel, Field, field_validator
import instructor
from openai import AsyncOpenAI


from datetime import datetime
from typing import List, Optional, Literal
from enum import Enum
from pydantic import BaseModel, Field


class NumericRange(BaseModel):
    gte: Optional[float] = None
    lte: Optional[float] = None
    gt: Optional[float] = None
    lt: Optional[float] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.model_dump(exclude_none=True).items()}


class NumericFilter(BaseModel):
    key: str = Field(
        description="The EXACT Qdrant payload key (e.g., 'data.average_glucose_mgdl', 'peak_glucose_mgdl')."
    )
    range_condition: NumericRange


# -----------------------------------------------------------------
class DateRange(BaseModel):
    start: datetime = Field(
        description="The inclusive start of the time period."
    )
    end: datetime = Field(description="The exclusive end of the time period.")


class TimeRange(BaseModel):
    start_hour: Optional[int] = None
    end_hour: Optional[int] = None


class SearchIntent(BaseModel):
    """Structured intent for hybrid search and filtering."""

    data_types: List[str] = Field(
        default_factory=list,
        description="List of exact 'data_type' values (e.g., ['cgm_summary_stats', 'hyper_event']).",
    )

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

    # query_type: QueryType = Field(
    #     description="Type of query: FILTER, HYBRID, or ANALYTICAL."
    # )

    month_filter: Optional[int] = Field(
        None,
        ge=1,
        le=12,
        description="The specific month number (1-12) mentioned in the query (e.g., 'September' is 9). Use this INSTEAD of date_range for month queries.",
    )

    time_buckets: List[str] = Field(
        default_factory=list,
        description="One or more time_of_day_bucket values (morning, afternoon, evening, night)",
    )


class IntentExtractor:
    def __init__(self, openai_client: AsyncOpenAI):
        self.client = instructor.from_openai(openai_client)

    async def extract(self, query: str) -> SearchIntent:
        current_date = datetime.now(timezone.utc).isoformat()

        system_prompt = f"""
        You are an intelligent CGM data query intent extractor. 
        Your SOLE task is to map the user's natural language request to the provided Pydantic schema.

        
        **CRITICAL INSTRUCTION:**
        1. If the query contains a relative date/time (e.g., "yesterday", "last week"), 
        resolve it using the Current context date/time: {current_date}.
        2. The date_range must always be absolute ISO 8601.
        
        **CRITICAL INSTRUCTION:**
        If the query contains multiple relevant CGM phenomena (e.g., "hypoglycemia" and "rapid drop"), include all matching data_types in the `data_types` list.  
        Do not select just one.  
        Always map using exact canonical data_types listed below.
        
        If the user specifies a time of day ("after dinner", "night", "morning", "afternoon", etc.), 
        map it to the closest canonical bucket in ["morning", "afternoon", "evening", "night"] as follows:

        - "breakfast", "morning" → "morning"
        - "lunch", "midday", "afternoon" → "afternoon"
        - "dinner", "evening" → "evening"
        - "after dinner", "late evening", "late night", "midnight", "night" → "night"
        
        If the user specifies a time range (e.g., "6am–9am"), parse the hours as integers and place them in `hour_range.start_hour` and `hour_range.end_hour`.  
        Use 24-hour format (0–23).  
        Do NOT use `time_of_day_bucket` for exact hour ranges.

        Here is the schema of available data:

        - data_type = "cgm_range_stats"
            - data.below_54_percent
            - data.below_70_above_54_percent
            - data.in_target_70_180_percent
            - data.above_180_below_250_percent
            - data.above_250_percent
            
        - data_type = "cgm_summary_stats"
            - data.average_glucose_mgdl
            - data.gmi
            - data.gmi_mmol
            - data.glucose_variability_percent
            - data.coefficient_of_variation_percent
            - data.std_dev_glucose_mgdl
            - data.highest_glucose_mgdl
            - data.highest_glucose_date
            - data.lowest_glucose_mgdl
            - data.lowest_glucose_date
        
        - data_type = "hyper_stats"
            - total_hyper_duration_minutes
            - hyper_events_count
            - average_hyper_duration_minutes
            
        - data_type = "hypo_stats"
            - total_hypo_duration_minutes
            - average_hypo_duration_minutes
            - hypo_events_count
        
        - data_type = "rapid_spike_stats"
            - total_spike_duration_minutes
            - average_spike_duration_minutes
            - spike_events_count
        
        - data_type = "rapid_drop_stats"
            - total_drop_duration_minutes
            - average_drop_duration_minutes
            - drop_events_count
            
        - data_type = "hyper_event"
            - duration_minutes
            - peak_glucose_mgdl
        
        - data_type = "hypo_event"
            - duration_minutes
            - lowest_glucose_mgdl
            
        - data_type = "rapid_spike_event"
            - duration_minutes
            - initial_glucose_mgdl
            - peak_glucose_mgdl
            - peak_glucose_time
        
        - data_type = "rapid_drop_event"
            - duration_minutes
            - initial_glucose_mgdl
            - lowest_glucose_mgdl
            - lowest_glucose_time
        
        - data_type = "time_period_stats"
            - time_period
            - data.average_glucose_mgdl
            - data.highest_glucose_mgdl
            - data.lowest_glucose_mgdl
            - data.out_of_range_percent
            - data.from_time
            - data.to_time
            
        - data_type = "agp_point"
            - hour
            - data.hour
            - data.median_mgdl
            - data.percentile_10_mgdl
            - data.percentile_25_mgdl
            - data.percentile_75_mgdl
            - data.percentile_90_mgdl

        NEVER invent new data_types or fields.
        """

        try:
            intent = await self.client.chat.completions.create(
                model="gpt-4o",
                response_model=SearchIntent,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                max_retries=2,
            )
            return intent
        except Exception as e:
            # Fallback for critical LLM failure after all retries
            print(f"Critical LLM failure after retries: {e}")
            return SearchIntent(
                semantic_query=query
            )  # type: ignore # Default to a safe search


from qdrant_client.http.models import FieldCondition as QdrantFieldCondition
from qdrant_client.http.models import Range as QdrantRange
from qdrant_client.http.models import MatchValue as QdrantMatchValue
from qdrant_client.http.models import MatchAny as QdrantMatchAny
from qdrant_client.http.models import Filter as QdrantFilter
from typing import Dict


# --- Helper to convert Pydantic to Qdrant Model ---
def _pydantic_to_qdrant_condition(
    key: str, value: Any
) -> QdrantFieldCondition:
    if isinstance(value, NumericRange):
        return QdrantFieldCondition(key=key, range=QdrantRange(**value.to_dict()))  # type: ignore
    if isinstance(value, str):
        return QdrantFieldCondition(
            key=key, match=QdrantMatchValue(value=value)
        )
    if isinstance(value, list):
        return QdrantFieldCondition(key=key, match=QdrantMatchAny(any=value))
    if isinstance(value, bool) or isinstance(value, int):
        return QdrantFieldCondition(
            key=key, match=QdrantMatchValue(value=value)
        )
    raise ValueError(f"Unsupported filter type for key {key}")


class FilterBuilder:
    @staticmethod
    def build(intent: SearchIntent) -> Optional[QdrantFilter]:
        must_conditions: List[QdrantFieldCondition] = []

        # 1. Data Type Filter
        if intent.data_types:
            must_conditions.append(
                QdrantFieldCondition(
                    key="data_type",
                    match=QdrantMatchAny(any=intent.data_types),
                )
            )

        # 2. Month Filter (Directly from the LLM's integer output)
        if intent.month_filter is not None:
            # We map the integer to a MatchValue filter
            must_conditions.append(
                QdrantFieldCondition(
                    key="month",
                    match=QdrantMatchValue(value=intent.month_filter),
                )
            )

        # 2. Date Range Filter (applies to all points)
        if intent.date_range:
            start_ms = int(intent.date_range.start.timestamp() * 1000)
            end_ms = int(intent.date_range.end.timestamp() * 1000)
            must_conditions.append(
                _pydantic_to_qdrant_condition(
                    "start_time", NumericRange(gte=float(start_ms))
                )
            )
            must_conditions.append(
                _pydantic_to_qdrant_condition(
                    "end_time", NumericRange(lte=float(end_ms))
                )
            )

        # 3. Time Bucket/Day Filters (e.g., "morning", "afternoon", "evening", "night")
        if intent.time_buckets:
            must_conditions.append(
                QdrantFieldCondition(
                    key="time_of_day_bucket",
                    match=QdrantMatchAny(any=intent.time_buckets),
                )
            )

        if intent.hour_range:
            must_conditions.append(
                QdrantFieldCondition(
                    key="hour",
                    range=NumericRange(
                        gte=float(intent.hour_range.start_hour),  # type: ignore
                        lt=float(intent.hour_range.end_hour),  # type: ignore
                    ).to_dict(),  # type: ignore
                )
            )

        # 4. Numeric Filters (The core metric constraints)
        for nf in intent.numeric_filters:
            range_dict = nf.range_condition.to_dict()
            if not range_dict:
                # skip, this is just the metric we’ll aggregate, not filter
                continue
            must_conditions.append(
                _pydantic_to_qdrant_condition(nf.key, nf.range_condition)
            )

        # 5. Final Filter Construction
        if must_conditions:
            # If complex 'should' logic (e.g., "filter must apply to EITHER event type 1 OR event type 2")
            # were needed, it would be built using the should_must_blocks structure here.
            # For simplicity, we assume the LLM correctly set the data_types and all numeric filters are MUSTs.
            return QdrantFilter(must=must_conditions)  # type: ignore

        return None
