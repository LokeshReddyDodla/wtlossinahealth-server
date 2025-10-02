from typing import Optional, List, Literal, Dict, Any
from pydantic import BaseModel, Field, field_validator, validator
from datetime import datetime, timezone, timedelta
from enum import Enum
import instructor
from openai import AsyncOpenAI
from qdrant_client.models import (
    Filter,
    FieldCondition,
    Range,
    MatchValue,
    MatchAny,
)
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# PART 1: INTENT EXTRACTION (LLM - What it's good at)
# ============================================================================


class DateRange(BaseModel):
    start: datetime
    end: datetime

    @field_validator("end")
    def end_after_start(cls, v, values):
        if "start" in values and v <= values["start"]:
            raise ValueError("end must be after start")
        return v


class NumericRange(BaseModel):
    gte: Optional[float] = None
    lte: Optional[float] = None
    gt: Optional[float] = None
    lt: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to Qdrant range format"""
        return {k: v for k, v in self.model_dump().items() if v is not None}


class QueryType(str, Enum):
    """What kind of search is needed"""

    FILTER_ONLY = "filter_only"  # "show events where glucose > 200"
    SEMANTIC_ONLY = "semantic_only"  # "explain my glucose patterns"
    HYBRID = "hybrid"  # "why did glucose spike after dinner in September"
    ANALYTICAL = "analytical"  # "compare weekdays vs weekends"


class SearchIntent(BaseModel):
    """Structured intent extracted from natural language"""

    query_type: QueryType = Field(
        description="Type of query: filter_only, semantic_only, hybrid, or analytical"
    )

    data_types: List[
        Literal[
            "cgm_range_stats",
            "cgm_summary_stats",
            "hyper_stats",
            "hypo_stats",
            "hyper_event",
            "hypo_event",
            "rapid_spike_stats",
            "rapid_spike_event",
            "rapid_drop_stats",
            "rapid_drop_event",
            "time_period_stats",
            "agp_point",
        ]
    ] = Field(
        default_factory=lambda: [], description="Types of data to search"
    )

    date_range: Optional[DateRange] = None
    glucose_range: Optional[NumericRange] = None
    duration_range_minutes: Optional[NumericRange] = None
    event_count_range: Optional[NumericRange] = None
    time_of_day_hours: Optional[NumericRange] = None

    # For semantic search
    semantic_query: Optional[str] = Field(
        None, description="Reformulated query for semantic search"
    )

    # For analytics
    comparison_type: Optional[
        Literal["weekday_vs_weekend", "before_after", "time_periods", "none"]
    ] = None

    @validator("data_types", pre=True, always=True)
    def expand_all_events(cls, v):
        """If empty and query needs events, add all event types"""
        if not v:
            return []
        if "all_events" in v:
            return [
                "hyper_event",
                "hypo_event",
                "rapid_spike_event",
                "rapid_drop_event",
            ]
        return v


class IntentExtractor:
    """Extract structured intent using LLM with instructor"""

    def __init__(self, openai_client: AsyncOpenAI):
        self.client = instructor.from_openai(openai_client)

    async def extract(self, query: str) -> SearchIntent:
        """Extract intent from natural language query"""

        current_date = datetime.now(timezone.utc)

        system_prompt = f"""You are a CGM query intent extractor. Extract structured information from user queries.

Current date: {current_date.isoformat()}

Guidelines:
1. Query Type Selection:
   - FILTER_ONLY: Precise conditions, no interpretation needed
     Examples: "glucose > 200", "events longer than 30 minutes", "hypo events in September"
   
   - SEMANTIC_ONLY: Asking for explanations, insights, patterns
     Examples: "explain my patterns", "what trends do you see", "why is this happening"
   
   - HYBRID: Combines filtering with semantic understanding
     Examples: "why did glucose spike after dinner in September", "explain high events"
   
   - ANALYTICAL: Comparing or analyzing multiple data segments
     Examples: "compare weekdays vs weekends", "before vs after medication change"

2. Date Handling:
   - "September" without year → use current year ({current_date.year})
   - "last week" → calculate from today
   - "last 7 days" → calculate from today
   - Relative dates like "yesterday", "last month" → calculate

3. Data Types:
   - "events" without specificity → ["hyper_event", "hypo_event", "rapid_spike_event", "rapid_drop_event"]
   - "stats" → include relevant stats types
   - Be specific when query mentions specific event types

4. Semantic Query:
   - For SEMANTIC_ONLY and HYBRID, rephrase the query to be more descriptive
   - Include context from filters in the semantic query

5. Ranges:
   - "below X" → lt: X
   - "above X" → gt: X
   - "between X and Y" → gte: X, lte: Y
   - "more than X events" → event_count_range with gt: X
"""

        try:
            intent = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                response_model=SearchIntent,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                max_retries=2,
            )

            logger.info(f"Extracted intent: {intent.dict()}")
            return intent

        except Exception as e:
            logger.error(f"Intent extraction failed: {e}")
            # Fallback: semantic search with no filters
            return SearchIntent(
                query_type=QueryType.SEMANTIC_ONLY, semantic_query=query
            )


# ============================================================================
# PART 2: DETERMINISTIC FILTER BUILDER (No LLM - Pure Logic)
# ============================================================================


class FilterBuilder:
    """Build Qdrant filters deterministically - NO LLM HALLUCINATIONS"""

    @staticmethod
    def build(intent: SearchIntent) -> Optional[Filter]:
        """Convert intent to Qdrant filter"""

        if not intent.data_types and not any(
            [
                intent.date_range,
                intent.glucose_range,
                intent.duration_range_minutes,
                intent.event_count_range,
                intent.time_of_day_hours,
            ]
        ):
            return None

        must_conditions = []
        should_conditions = []

        # Build data type filter
        if intent.data_types:
            if len(intent.data_types) == 1:
                must_conditions.append(
                    FieldCondition(
                        key="data_type",
                        match=MatchValue(value=intent.data_types[0]),
                    )
                )
            else:
                # Multiple types - use MatchAny (more efficient than should)
                must_conditions.append(
                    FieldCondition(
                        key="data_type", match=MatchAny(any=intent.data_types)
                    )
                )

        # Date range filter
        if intent.date_range:
            start_ms = int(intent.date_range.start.timestamp() * 1000)
            end_ms = int(intent.date_range.end.timestamp() * 1000)

            must_conditions.append(
                FieldCondition(key="start_time", range=Range(gte=start_ms))
            )
            must_conditions.append(
                FieldCondition(key="end_time", range=Range(lte=end_ms))
            )

        # Glucose range (context-aware based on data type)
        if intent.glucose_range and intent.data_types:
            glucose_conditions = FilterBuilder._build_glucose_conditions(
                intent.data_types, intent.glucose_range
            )
            if glucose_conditions:
                if len(glucose_conditions) == 1:
                    must_conditions.append(glucose_conditions[0])
                else:
                    should_conditions.extend(glucose_conditions)

        # Duration filter (always in minutes, never convert to ms!)
        if intent.duration_range_minutes:
            duration_condition = FilterBuilder._build_duration_condition(
                intent.data_types, intent.duration_range_minutes
            )
            if duration_condition:
                must_conditions.append(duration_condition)

        # Event count filter
        if intent.event_count_range and intent.data_types:
            count_condition = FilterBuilder._build_event_count_condition(
                intent.data_types, intent.event_count_range
            )
            if count_condition:
                must_conditions.append(count_condition)

        # Time of day (for AGP points)
        if intent.time_of_day_hours:
            must_conditions.append(
                FieldCondition(
                    key="hour",
                    range=Range(**intent.time_of_day_hours.to_dict()),
                )
            )

        # Construct final filter
        if should_conditions and must_conditions:
            # Combine should and must
            return Filter(must=must_conditions, should=should_conditions)
        elif should_conditions:
            return Filter(should=should_conditions)
        elif must_conditions:
            return Filter(must=must_conditions)

        return None

    @staticmethod
    def _build_glucose_conditions(
        data_types: List[str], glucose_range: NumericRange
    ) -> List[FieldCondition]:
        """Build glucose filter based on data type context"""
        conditions = []

        for data_type in data_types:
            key = None

            if data_type in ["hyper_event", "rapid_spike_event"]:
                key = "peak_glucose_level"
            elif data_type in ["hypo_event", "rapid_drop_event"]:
                key = "lowest_glucose_level"
            elif data_type == "cgm_summary_stats":
                key = "data.average_glucose"
            elif data_type == "rapid_spike_event":
                key = "initial_glucose_level"  # Could also filter peak

            if key:
                conditions.append(
                    FieldCondition(
                        key=key, range=Range(**glucose_range.to_dict())
                    )
                )

        return conditions

    @staticmethod
    def _build_duration_condition(
        data_types: List[str], duration_range: NumericRange
    ) -> Optional[FieldCondition]:
        """Build duration filter (always in minutes)"""

        # For events, use direct duration field
        if any("event" in dt for dt in data_types):
            return FieldCondition(
                key="duration", range=Range(**duration_range.to_dict())
            )

        # For stats, use appropriate duration field
        for data_type in data_types:
            if data_type == "hyper_stats":
                return FieldCondition(
                    key="data.average_hyper_duration",
                    range=Range(**duration_range.to_dict()),
                )
            elif data_type == "hypo_stats":
                return FieldCondition(
                    key="data.average_hypo_duration",
                    range=Range(**duration_range.to_dict()),
                )

        return None

    @staticmethod
    def _build_event_count_condition(
        data_types: List[str], count_range: NumericRange
    ) -> Optional[FieldCondition]:
        """Build event count filter"""

        for data_type in data_types:
            if data_type == "hyper_stats":
                return FieldCondition(
                    key="data.hyper_events_count",
                    range=Range(**count_range.to_dict()),
                )
            elif data_type == "hypo_stats":
                return FieldCondition(
                    key="data.hypo_events_count",
                    range=Range(**count_range.to_dict()),
                )
            elif data_type == "rapid_spike_stats":
                return FieldCondition(
                    key="data.spike_events_count",
                    range=Range(**count_range.to_dict()),
                )
            elif data_type == "rapid_drop_stats":
                return FieldCondition(
                    key="data.drop_events_count",
                    range=Range(**count_range.to_dict()),
                )

        return None


# ============================================================================
# PART 3: SEARCH ENGINE (Orchestrates Everything)
# ============================================================================


class CGMSearchEngine:
    """Main search engine - coordinates intent extraction and filtering"""

    def __init__(
        self,
        openai_client: AsyncOpenAI,
        vector_service,  # Your CGMReportVectorService
    ):
        self.intent_extractor = IntentExtractor(openai_client)
        self.filter_builder = FilterBuilder()
        self.vector_service = vector_service
        self.openai_client = openai_client

    async def search(
        self,
        query: str,
        limit: int = 10,
        score_threshold: float = 0.7,
    ) -> Dict[str, Any]:
        """
        Main search method - returns results + metadata for LangChain
        """

        # Step 1: Extract intent (LLM does what it's good at)
        intent = await self.intent_extractor.extract(query)

        # Step 2: Build filter (deterministic, no hallucinations)
        filter_conditions = self.filter_builder.build(intent)

        # Step 3: Get embedding if needed
        embedding = None
        if intent.query_type in [QueryType.SEMANTIC_ONLY, QueryType.HYBRID]:
            # Use semantic query if available, otherwise original query
            search_text = intent.semantic_query or query

            response = await self.openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=search_text,
            )
            embedding = response.data[0].embedding

        # Step 4: Search Qdrant
        if embedding is None and filter_conditions is None:
            # Fallback: at least do semantic search
            response = await self.openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=query,
            )
            embedding = response.data[0].embedding

        results = await self.vector_service.search_similar_reports(
            query_embedding=embedding,
            filter_conditions=filter_conditions,
            limit=limit,
            score_threshold=score_threshold if embedding else None,
        )

        # Step 5: Format for LangChain
        return {
            "query": query,
            "intent": intent.dict(),
            "filter": filter_conditions.dict() if filter_conditions else None,
            "results": results,
            "metadata": {
                "query_type": intent.query_type,
                "used_semantic_search": embedding is not None,
                "used_filters": filter_conditions is not None,
                "result_count": len(results),
            },
        }

    async def search_for_langchain(
        self,
        query: str,
        limit: int = 10,
    ) -> str:
        """
        Format results for LangChain context - returns formatted string
        """
        search_result = await self.search(query, limit)

        # Format results as context
        context_parts = [f"Query: {query}\n"]

        if search_result["results"]:
            context_parts.append(
                f"Found {len(search_result['results'])} relevant results:\n"
            )

            for i, result in enumerate(search_result["results"], 1):
                score = result.score if hasattr(result, "score") else "N/A"
                payload = result.payload

                context_parts.append(f"\n{i}. {payload.get('text_repr', '')}")
                context_parts.append(
                    f"   Data Type: {payload.get('data_type')}"
                )
                context_parts.append(f"   Relevance: {score}")

                # Add specific metrics based on data type
                if "data" in payload:
                    context_parts.append(f"   Metrics: {payload['data']}")
        else:
            context_parts.append("No matching results found.")

        return "\n".join(context_parts)
