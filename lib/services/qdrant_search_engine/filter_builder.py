from typing import Any, Optional, List
from qdrant_client.http.models import FieldCondition as QdrantFieldCondition
from qdrant_client.http.models import Range as QdrantRange
from qdrant_client.http.models import MatchValue as QdrantMatchValue
from qdrant_client.http.models import MatchAny as QdrantMatchAny
from qdrant_client.http.models import Filter as QdrantFilter

from lib.services.qdrant_search_engine.models import NumericRange, SearchIntent


def _pydantic_to_qdrant_condition(
    key: str, value: Any
) -> QdrantFieldCondition:
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
    @staticmethod
    def build(intent: SearchIntent) -> Optional[QdrantFilter]:
        """
        Build a QdrantFilter from a SearchIntent.
        """
        FilterBuilder.enforce_stats_events_rule(intent)

        must_conditions: List[QdrantFieldCondition] = []

        FilterBuilder._add_data_type_filter(intent, must_conditions)
        # FilterBuilder._add_source_filter(intent, must_conditions)
        FilterBuilder._add_month_filter(intent, must_conditions)
        FilterBuilder._add_date_range_filter(intent, must_conditions)
        FilterBuilder._add_time_filters(intent, must_conditions)
        FilterBuilder._add_numeric_filters(intent, must_conditions)

        if must_conditions:
            return QdrantFilter(must=must_conditions)  # type: ignore
        return None

    @staticmethod
    def _add_data_type_filter(
        intent: SearchIntent, conditions: List[QdrantFieldCondition]
    ):
        if intent.data_types:
            conditions.append(
                QdrantFieldCondition(
                    key="data_type",
                    match=QdrantMatchAny(any=intent.data_types),
                )
            )

    # @staticmethod
    # def _add_source_filter(
    #     intent: SearchIntent, conditions: List[QdrantFieldCondition]
    # ):
    #     if intent.sources:
    #         if len(intent.sources) == 1:
    #             conditions.append(
    #                 QdrantFieldCondition(
    #                     key="source",
    #                     match=QdrantMatchValue(value=intent.sources[0]),
    #                 )
    #             )
    #         else:
    #             conditions.append(
    #                 QdrantFieldCondition(
    #                     key="source",
    #                     match=QdrantMatchAny(any=intent.sources),
    #                 )
    #             )

    @staticmethod
    def _add_month_filter(
        intent: SearchIntent, conditions: List[QdrantFieldCondition]
    ):
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
        intent: SearchIntent, conditions: List[QdrantFieldCondition]
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
    def _add_time_filters(
        intent: SearchIntent, conditions: List[QdrantFieldCondition]
    ):
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
                    range=NumericRange(
                        gte=float(intent.hour_range.start_hour),
                        lt=float(intent.hour_range.end_hour),
                    ).to_dict(),  # type: ignore
                )
            )

    @staticmethod
    def _add_numeric_filters(
        intent: SearchIntent, conditions: List[QdrantFieldCondition]
    ):
        for nf in intent.numeric_filters:
            if nf.range_condition.to_dict():
                conditions.append(
                    _pydantic_to_qdrant_condition(nf.key, nf.range_condition)
                )

    @staticmethod
    def enforce_stats_events_rule(intent: SearchIntent):
        dt_set = set(intent.data_types)

        if any("hyper" in dt for dt in dt_set):
            dt_set.update({"hyper_stats", "hyper_event"})

        if any("hypo" in dt for dt in dt_set):
            dt_set.update({"hypo_stats", "hypo_event"})

        if any("rapid_spike" in dt for dt in dt_set):
            dt_set.update({"rapid_spike_stats", "rapid_spike_event"})

        if any("rapid_drop" in dt for dt in dt_set):
            dt_set.update({"rapid_drop_stats", "rapid_drop_event"})

        intent.data_types = list(dt_set)
