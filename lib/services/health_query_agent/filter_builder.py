from typing import Any, Optional, List, Set
from qdrant_client.http.models import (
    FieldCondition as QdrantFieldCondition,
    Range as QdrantRange,
    MatchValue as QdrantMatchValue,
    MatchAny as QdrantMatchAny,
    Filter as QdrantFilter,
    MinShould as QdrantMinShould,
)

from lib.services.health_query_agent.intent import NumericRange

from .schemas import QueryIntent, HealthDataType


def _pydantic_to_qdrant_condition(key: str, value: Any) -> QdrantFieldCondition:
    """Convert a Pydantic value to a Qdrant field condition."""
    if isinstance(value, NumericRange):
        return QdrantFieldCondition(key=key, range=QdrantRange(**value.to_dict()))

    if isinstance(value, str):
        return QdrantFieldCondition(key=key, match=QdrantMatchValue(value=value))

    if isinstance(value, list):
        return QdrantFieldCondition(key=key, match=QdrantMatchAny(any=value))

    if isinstance(value, (bool, int, float)):
        return QdrantFieldCondition(key=key, match=QdrantMatchValue(value=value))  # type: ignore

    raise ValueError(
        f"Unsupported filter type for key '{key}' with value type {type(value).__name__}"
    )


class FilterBuilder:
    # Data types that should NEVER receive time/date filters
    NON_FILTERABLE_TYPES: Set[HealthDataType] = {
        HealthDataType.PROFILE,
        HealthDataType.DOCUMENTS,
    }

    @staticmethod
    def build(intent: QueryIntent) -> Optional[QdrantFilter]:
        FilterBuilder.enforce_stats_events_rule(intent)

        should_filters: List[QdrantFilter] = []

        # Data types that should NEVER receive time/date filters
        static_types = [
            dt.value
            for dt in intent.data_types
            if dt in FilterBuilder.NON_FILTERABLE_TYPES
        ]

        if static_types:
            should_filters.append(
                QdrantFilter(
                    must=[
                        QdrantFieldCondition(
                            key="data_type",
                            match=QdrantMatchAny(any=static_types),
                        )
                    ]
                )
            )

        # Data types that should receive time/date filters
        timeseries_conditions: List[QdrantFieldCondition] = []

        timeseries_types = [
            dt.value
            for dt in intent.data_types
            if dt not in FilterBuilder.NON_FILTERABLE_TYPES
        ]

        if timeseries_types:
            timeseries_conditions.append(
                QdrantFieldCondition(
                    key="data_type",
                    match=QdrantMatchAny(any=timeseries_types),
                )
            )

            FilterBuilder._add_month_filter(intent, timeseries_conditions)
            FilterBuilder._add_date_range_filter(intent, timeseries_conditions)
            FilterBuilder._add_time_filters(intent, timeseries_conditions)
            FilterBuilder._add_numeric_filters(intent, timeseries_conditions)

            should_filters.append(QdrantFilter(should=timeseries_conditions))

        if not should_filters:
            return None

        return QdrantFilter(
            should=should_filters,
            min_should=QdrantMinShould(value=1),
        )


    @staticmethod
    def _add_month_filter(intent: QueryIntent, conditions: List[QdrantFieldCondition]):
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
    def _add_time_filters(intent: QueryIntent, conditions: List[QdrantFieldCondition]):
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
                    ),
                )
            )

    @staticmethod
    def _add_numeric_filters(
        intent: QueryIntent, conditions: List[QdrantFieldCondition]
    ):
        for nf in intent.numeric_filters:
            if nf.range_condition.to_dict():
                conditions.append(
                    _pydantic_to_qdrant_condition(nf.key, nf.range_condition)
                )

    @staticmethod
    def enforce_stats_events_rule(intent: QueryIntent):
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
