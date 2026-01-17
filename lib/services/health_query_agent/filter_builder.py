"""
Filter builder for converting QueryIntent to Qdrant filters.
"""
from typing import Any, Optional, List
from qdrant_client.http.models import (
    FieldCondition as QdrantFieldCondition,
    Range as QdrantRange,
    MatchValue as QdrantMatchValue,
    MatchAny as QdrantMatchAny,
    Filter as QdrantFilter,
)

from lib.services.qdrant_search_engine.models import NumericRange
from .schemas import QueryIntent, HealthDataType


def _pydantic_to_qdrant_condition(
    key: str, value: Any
) -> QdrantFieldCondition:
    """Convert a Pydantic value to a Qdrant field condition."""
    if isinstance(value, NumericRange):
        return QdrantFieldCondition(
            key=key, range=QdrantRange(**value.to_dict())
        )

    if isinstance(value, str):
        return QdrantFieldCondition(
            key=key, match=QdrantMatchValue(value=value)
        )

    if isinstance(value, list):
        return QdrantFieldCondition(key=key, match=QdrantMatchAny(any=value))

    if isinstance(value, (bool, int, float)):
        return QdrantFieldCondition(key=key, match=QdrantMatchValue(value=value))  # type: ignore

    raise ValueError(
        f"Unsupported filter type for key '{key}' with value type {type(value).__name__}"
    )


class FilterBuilder:
    """Builder for creating Qdrant filters from QueryIntent."""
    
    @staticmethod
    def build(intent: QueryIntent) -> Optional[QdrantFilter]:
        """Build a QdrantFilter from a QueryIntent."""
        FilterBuilder.enforce_stats_events_rule(intent)

        must_conditions: List[QdrantFieldCondition] = []

        FilterBuilder._add_data_type_filter(intent, must_conditions)
        FilterBuilder._add_month_filter(intent, must_conditions)
        FilterBuilder._add_date_range_filter(intent, must_conditions)
        FilterBuilder._add_time_filters(intent, must_conditions)

        if must_conditions:
            return QdrantFilter(must=must_conditions)  # type: ignore
        return None

    @staticmethod
    def _add_data_type_filter(
        intent: QueryIntent, conditions: List[QdrantFieldCondition]
    ):
        """Add data type filter conditions."""
        data_types_with_profile = set(intent.data_types)
        data_types_with_profile.add(HealthDataType.PROFILE)
        
        conditions.append(
            QdrantFieldCondition(
                key="data_type",
                match=QdrantMatchAny(any=[dt.value for dt in data_types_with_profile]),
            )
        )

    @staticmethod
    def _add_month_filter(
        intent: QueryIntent, conditions: List[QdrantFieldCondition]
    ):
        """Add month filter conditions."""
        if intent.month_filters:
            # If only one month, match that directly
            if len(intent.month_filters) == 1:
                conditions.append(
                    QdrantFieldCondition(
                        key="month",
                        match=QdrantMatchValue(value=intent.month_filters[0]),
                    )
                )
            else:
                # If multiple months, use MatchAny
                conditions.append(
                    QdrantFieldCondition(
                        key="month",
                        match=QdrantMatchAny(any=intent.month_filters),
                    )
                )

    @staticmethod
    def _add_date_range_filter(
        intent: QueryIntent, conditions: List[QdrantFieldCondition]
    ):
        """Add date range filter conditions."""
        if intent.date_range:
            start_ms = int(intent.date_range.start.timestamp() * 1000)
            end_ms = int(intent.date_range.end.timestamp() * 1000)

            conditions.append(
                _pydantic_to_qdrant_condition(
                    "start_time", NumericRange(gte=float(start_ms))
                )
            )
            conditions.append(
                _pydantic_to_qdrant_condition(
                    "end_time", NumericRange(lte=float(end_ms))
                )
            )

    @staticmethod
    def _add_time_filters(
        intent: QueryIntent, conditions: List[QdrantFieldCondition]
    ):
        """Add time-related filter conditions."""
        if intent.time_buckets:
            conditions.append(
                QdrantFieldCondition(
                    key="time_of_day_bucket",
                    match=QdrantMatchAny(any=intent.time_buckets),
                )
            )

        if (
            intent.hour_range
            and intent.hour_range.start_hour is not None
            and intent.hour_range.end_hour is not None
        ):
            conditions.append(
                QdrantFieldCondition(
                    key="hour",
                    range=QdrantRange(
                        gte=float(intent.hour_range.start_hour),
                        lt=float(intent.hour_range.end_hour),
                    )
                )
            )

    @staticmethod
    def enforce_stats_events_rule(intent: QueryIntent):
        """
        Enforce the rule that certain data types should include their 
        corresponding stats and event types.
        """
        dt_set = set(intent.data_types)

        if any("hyper" in dt.value for dt in dt_set):
            dt_set.add(HealthDataType.HYPER_STATS)
            dt_set.add(HealthDataType.HYPER_EVENT)

        if any("hypo" in dt.value for dt in dt_set):
            dt_set.add(HealthDataType.HYPO_STATS)
            dt_set.add(HealthDataType.HYPO_EVENT)

        if any("rapid_spike" in dt.value for dt in dt_set):
            dt_set.add(HealthDataType.RAPID_SPIKE)
            dt_set.add(HealthDataType.RAPID_SPIKE_EVENT)

        if any("rapid_drop" in dt.value for dt in dt_set):
            dt_set.add(HealthDataType.RAPID_DROP)
            dt_set.add(HealthDataType.RAPID_DROP_EVENT)

        intent.data_types = list(dt_set)
