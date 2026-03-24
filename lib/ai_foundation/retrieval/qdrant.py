"""
Qdrant Retriever — semantic vector search over patient health data.

Wraps the QdrantStore from lib/core and the embed_text utility to provide
a standard Retriever interface. Uses the actual Qdrant filter models and
the async context manager pattern from QdrantStore.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Awaitable

from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchAny,
    Range,
)

from .base import RetrievalRequest, RetrievalResult

if TYPE_CHECKING:
    from lib.core.qdrant_store import QdrantStore
    from lib.ai_foundation.cache.embedding_cache import EmbeddingCache

logger = logging.getLogger(__name__)

# Type alias for the embedding function
EmbedFn = Callable[[str], Awaitable[list[float]]]


def _date_str_to_epoch_ms(date_str: str) -> float | None:
    """Convert an ISO date string to epoch milliseconds for Qdrant filtering.

    Qdrant stores timestamps as start_time/end_time in epoch milliseconds.
    Handles both date-only ("2026-03-20") and datetime ("2026-03-20T00:00:00Z") formats.
    """
    try:
        if "T" in date_str:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt.timestamp() * 1000
    except (ValueError, AttributeError):
        return None


class QdrantRetriever:
    """Semantic search retriever backed by Qdrant vector database.

    Uses QdrantStore's async context manager for the client and proper
    qdrant_client filter models for type safety.

    Args:
        qdrant_store: The ``QdrantStore`` singleton from ``lib/core``.
        collection_name: Qdrant collection to search (default: from env).
        embedding_fn: Async callable ``(text) -> list[float]``. Use
            ``lib.utils.vector_utils.embed_text``.
        embedding_cache: Optional cache to skip redundant embedding calls.
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

    async def retrieve(self, request: RetrievalRequest) -> list[RetrievalResult]:
        """Execute semantic search against Qdrant."""
        if self._embed_fn is None:
            raise RuntimeError("QdrantRetriever requires an embedding_fn.")

        query_vector = await self._get_embedding(request.query)
        search_filter = self._build_filter(request)

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
            results.append(
                RetrievalResult(
                    payload=payload,
                    source="qdrant",
                    score=point.score,
                    data_type=payload.get("data_type"),
                )
            )

        logger.debug(
            "Qdrant search: %d results (top_score=%.3f)",
            len(results),
            results[0].score if results else 0.0,
        )
        return results

    async def _get_embedding(self, text: str) -> list[float]:
        """Get embedding vector, using cache if available."""
        if self._embed_cache:
            cached = self._embed_cache.get(text)
            if cached is not None:
                return cached
            vector = await self._embed_fn(text)
            self._embed_cache.set(text, vector)
            return vector
        return await self._embed_fn(text)

    @staticmethod
    def _build_filter(request: RetrievalRequest) -> Filter | None:
        """Build a Qdrant Filter from the retrieval request."""
        must: list[FieldCondition] = []

        if request.patient_ids:
            must.append(FieldCondition(
                key="patient_id",
                match=MatchAny(any=request.patient_ids),
            ))

        if request.data_types:
            must.append(FieldCondition(
                key="data_type",
                match=MatchAny(any=request.data_types),
            ))

        # Qdrant stores dates as epoch milliseconds in start_time/end_time fields
        if request.date_start:
            start_ms = _date_str_to_epoch_ms(request.date_start)
            if start_ms is not None:
                must.append(FieldCondition(
                    key="start_time",
                    range=Range(gte=start_ms),
                ))

        if request.date_end:
            end_ms = _date_str_to_epoch_ms(request.date_end)
            if end_ms is not None:
                must.append(FieldCondition(
                    key="end_time",
                    range=Range(lte=end_ms),
                ))

        # Pass-through extra filters
        for key, value in request.filters.items():
            if isinstance(value, dict) and "range" in value:
                must.append(FieldCondition(key=key, range=Range(**value["range"])))
            elif isinstance(value, list):
                must.append(FieldCondition(key=key, match=MatchAny(any=value)))
            else:
                must.append(FieldCondition(key=key, match=MatchAny(any=[value])))

        return Filter(must=must) if must else None
