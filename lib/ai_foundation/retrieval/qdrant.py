"""
Qdrant Retriever — primary data source for all health queries.

Two retrieval modes:
1. Filtered Scroll — deterministic queries (90% of queries)
   Uses qdrant.scroll() with indexed filters. No embedding needed.
   "Show meals today", "Glucose this week" → exact records with full payloads.

2. Semantic Search — cross-domain/pattern queries (10% of queries)
   Uses qdrant.search() with vector similarity + filters.
   "Find patterns between meals and glucose" → relevance-ranked results.

Filter building ported from v2/filter_builder.py — handles date ranges,
time buckets, hour ranges, month filters, numeric constraints, and the
stats/events pairing rule.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Awaitable

from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    Range,
)

from .base import RetrievalRequest, RetrievalResult

if TYPE_CHECKING:
    from lib.core.qdrant_store import QdrantStore
    from lib.ai_foundation.cache.embedding_cache import EmbeddingCache

logger = logging.getLogger(__name__)

EmbedFn = Callable[[str], Awaitable[list[float]]]

# Data types that need stats+events pairing
_STATS_EVENTS_PAIRS = {
    "hyper": ["hyper_stats", "hyper_event"],
    "hypo": ["hypo_stats", "hypo_event"],
    "rapid_spike": ["rapid_spike_stats", "rapid_spike_event"],
    "rapid_drop": ["rapid_drop_stats", "rapid_drop_event"],
}

# Data types that don't support time-based filtering
_NON_FILTERABLE_TYPES = {"profile", "patient_document"}


def _date_to_epoch_ms(dt: datetime) -> float:
    """Convert datetime to epoch milliseconds."""
    return dt.timestamp() * 1000


def _date_str_to_epoch_ms(date_str: str, *, end_of_day: bool = False) -> float | None:
    """Convert ISO date string to epoch milliseconds.

    Args:
        date_str: ISO date or datetime string.
        end_of_day: If True and date_str has no time component,
                    use 23:59:59 UTC instead of 00:00:00 UTC.
                    This is critical for date_end filters — a date_end
                    of "2026-03-25" should include the entire day.
    """
    try:
        if "T" in date_str:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            # Ensure timezone-aware (naive datetimes use local tz in .timestamp())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
        return dt.timestamp() * 1000
    except (ValueError, AttributeError):
        return None


def _expand_data_types(data_types: list[str]) -> list[str]:
    """Apply stats/events pairing rule.

    If "hypo" is requested, also include "hypo_stats" and "hypo_event".
    """
    expanded = set(data_types)
    for prefix, pair_types in _STATS_EVENTS_PAIRS.items():
        if any(dt == prefix or dt.startswith(prefix + "_") for dt in data_types):
            expanded.update(pair_types)
    return list(expanded)


class QdrantRetriever:
    """Primary data retriever using Qdrant with two modes.

    Args:
        qdrant_store: QdrantStore singleton from lib/core.
        collection_name: Qdrant collection (default: from env).
        embedding_fn: Async callable for semantic search mode.
        embedding_cache: Optional cache for embeddings.
    """

    name: str = "qdrant"

    def __init__(
        self,
        *,
        qdrant_store: QdrantStore,
        collection_name: str = "patient_data",
        embedding_fn: EmbedFn | None = None,
        embedding_cache: EmbeddingCache | None = None,
    ) -> None:
        self._store = qdrant_store
        self._collection = collection_name
        self._embed_fn = embedding_fn
        self._embed_cache = embedding_cache

    # ── Mode 1: Filtered Scroll (deterministic) ──────────────────────────

    async def retrieve_filtered(self, request: RetrievalRequest) -> list[RetrievalResult]:
        """Filtered scroll — no embedding, no vector similarity.

        Uses indexed filters for fast exact retrieval. This is the primary
        mode for 90% of health queries.
        """
        scroll_filter = self._build_full_filter(request)
        if not scroll_filter:
            return []

        async with self._store.get_client() as client:
            scroll_kwargs: dict[str, Any] = {
                "collection_name": self._collection,
                "scroll_filter": scroll_filter,
                "limit": request.limit,
                "with_payload": True,
                "with_vectors": False,
            }

            # Order by start_time DESC so the limit keeps the most recent records.
            # Falls back to unordered scroll if OrderBy is unavailable or server rejects it.
            try:
                from qdrant_client.models import OrderBy
                scroll_kwargs["order_by"] = OrderBy(key="start_time", direction="desc")
                records, _ = await client.scroll(**scroll_kwargs)
            except (ImportError, TypeError) as exc:
                logger.debug("OrderBy not supported, falling back to unordered scroll: %s", exc)
                scroll_kwargs.pop("order_by", None)
                records, _ = await client.scroll(**scroll_kwargs)
            except Exception as exc:
                # If first scroll failed for non-OrderBy reasons, try without it once
                if "order_by" in scroll_kwargs:
                    logger.debug("Scroll with OrderBy failed (%s), retrying without", exc)
                    scroll_kwargs.pop("order_by", None)
                    records, _ = await client.scroll(**scroll_kwargs)
                else:
                    raise

        results: list[RetrievalResult] = []
        for record in records:
            payload = record.payload or {}
            results.append(RetrievalResult(
                payload=payload,
                source="qdrant_filtered",
                score=None,
                data_type=payload.get("data_type"),
            ))

        logger.debug("Qdrant filtered scroll: %d results", len(results))
        return results

    # ── Mode 2: Semantic Search (cross-domain) ───────────────────────────

    async def retrieve(self, request: RetrievalRequest) -> list[RetrievalResult]:
        """Semantic vector search — for pattern/correlation queries."""
        if self._embed_fn is None:
            raise RuntimeError("QdrantRetriever requires an embedding_fn for semantic search.")

        query_vector = await self._get_embedding(request.query)
        search_filter = self._build_full_filter(request)

        async with self._store.get_client() as client:
            search_result = await client.search(
                collection_name=self._collection,
                query_vector=query_vector,
                query_filter=search_filter,
                limit=request.limit,
                with_payload=True,
            )

        results: list[RetrievalResult] = []
        for point in search_result:
            payload = point.payload or {}
            results.append(RetrievalResult(
                payload=payload,
                source="qdrant_semantic",
                score=point.score,
                data_type=payload.get("data_type"),
            ))

        logger.debug(
            "Qdrant semantic search: %d results (top_score=%.3f)",
            len(results),
            results[0].score if results else 0.0,
        )
        return results

    # ── Filter Building ──────────────────────────────────────────────────

    def _build_full_filter(self, request: RetrievalRequest) -> Filter | None:
        """Build comprehensive Qdrant filter from the retrieval request.

        Ported from v2/filter_builder.py with full support for:
        - Patient ID, data types (with stats/events expansion)
        - Date range (epoch ms), month filters
        - Time buckets, hour ranges
        - Numeric filters (range conditions)
        - Non-filterable types (PROFILE, DOCUMENTS) via should/min_should
        """
        if not request.patient_ids:
            return None

        data_types = _expand_data_types(request.data_types) if request.data_types else []

        # Separate filterable vs non-filterable types
        non_filterable = [dt for dt in data_types if dt in _NON_FILTERABLE_TYPES]
        filterable = [dt for dt in data_types if dt not in _NON_FILTERABLE_TYPES]

        should_filters: list[Filter] = []

        # Always include profile data
        should_filters.append(Filter(must=[
            FieldCondition(key="patient_id", match=MatchAny(any=request.patient_ids)),
            FieldCondition(key="data_type", match=MatchValue(value="profile")),
        ]))

        # Non-filterable types (documents, etc.)
        if non_filterable:
            should_filters.append(Filter(must=[
                FieldCondition(key="patient_id", match=MatchAny(any=request.patient_ids)),
                FieldCondition(key="data_type", match=MatchAny(any=non_filterable)),
            ]))

        # Filterable types (timeseries data with date/time filters)
        if filterable or not data_types:
            must: list[FieldCondition] = [
                FieldCondition(key="patient_id", match=MatchAny(any=request.patient_ids)),
            ]

            if filterable:
                must.append(FieldCondition(key="data_type", match=MatchAny(any=filterable)))

            # Date range → epoch ms
            if request.date_start:
                start_ms = _date_str_to_epoch_ms(request.date_start)
                if start_ms is not None:
                    must.append(FieldCondition(key="start_time", range=Range(gte=start_ms)))

            if request.date_end:
                end_ms = _date_str_to_epoch_ms(request.date_end, end_of_day=True)
                if end_ms is not None:
                    must.append(FieldCondition(key="end_time", range=Range(lte=end_ms)))

            # Month filters
            month_filters = request.filters.get("month_filters")
            if month_filters:
                if isinstance(month_filters, list) and len(month_filters) == 1:
                    must.append(FieldCondition(key="month", match=MatchValue(value=month_filters[0])))
                elif isinstance(month_filters, list):
                    must.append(FieldCondition(key="month", match=MatchAny(any=month_filters)))

            # Time buckets
            time_buckets = request.filters.get("time_buckets")
            if time_buckets and isinstance(time_buckets, list):
                must.append(FieldCondition(key="time_of_day_bucket", match=MatchAny(any=time_buckets)))

            # Hour range
            hour_start = request.filters.get("hour_start")
            hour_end = request.filters.get("hour_end")
            if hour_start is not None and hour_end is not None:
                must.append(FieldCondition(key="hour", range=Range(
                    gte=float(hour_start), lt=float(hour_end),
                )))

            # Numeric filters (e.g., glucose > 200)
            numeric_filters = request.filters.get("numeric_filters")
            if numeric_filters and isinstance(numeric_filters, list):
                for nf in numeric_filters:
                    key = nf.get("key")
                    range_cond = nf.get("range_condition", {})
                    if key and range_cond:
                        range_kwargs = {}
                        for op in ("gte", "lte", "gt", "lt"):
                            if op in range_cond and range_cond[op] is not None:
                                range_kwargs[op] = float(range_cond[op])
                        if range_kwargs:
                            must.append(FieldCondition(key=key, range=Range(**range_kwargs)))

            # Other pass-through filters
            for key, value in request.filters.items():
                if key in ("month_filters", "time_buckets", "hour_start", "hour_end", "numeric_filters"):
                    continue  # already handled above
                if isinstance(value, list):
                    must.append(FieldCondition(key=key, match=MatchAny(any=value)))
                elif isinstance(value, (int, float, str, bool)):
                    must.append(FieldCondition(key=key, match=MatchValue(value=value)))

            should_filters.append(Filter(must=must))

        # Combine with should (OR logic: match profile OR timeseries OR documents)
        if len(should_filters) == 1:
            return should_filters[0]

        try:
            from qdrant_client.models import MinShould
            return Filter(
                should=should_filters,
                min_should=MinShould(min_count=1, conditions=should_filters),
            )
        except ImportError:
            # Older qdrant-client — use should without min_should
            return Filter(should=should_filters)

    # ── Embedding helpers ────────────────────────────────────────────────

    async def _get_embedding(self, text: str) -> list[float]:
        if self._embed_cache:
            cached = self._embed_cache.get(text)
            if cached is not None:
                return cached
            vector = await self._embed_fn(text)
            self._embed_cache.set(text, vector)
            return vector
        return await self._embed_fn(text)
