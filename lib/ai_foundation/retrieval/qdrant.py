"""
Qdrant Retriever — semantic vector search over patient health data.

Wraps the QdrantStore from lib/core and provides a standard Retriever
interface. Supports filtering by patient_id, data_types, date ranges,
and arbitrary payload filters.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .base import RetrievalRequest, RetrievalResult

if TYPE_CHECKING:
    from lib.core.qdrant_store import QdrantStore
    from lib.ai_foundation.cache.embedding_cache import EmbeddingCache

logger = logging.getLogger(__name__)


class QdrantRetriever:
    """Semantic search retriever backed by Qdrant vector database.

    Args:
        qdrant_store: The ``QdrantStore`` instance from ``lib/core``.
        collection_name: Qdrant collection to search.
        embedding_fn: Async callable that takes text and returns an embedding vector.
        embedding_cache: Optional ``EmbeddingCache`` to avoid redundant embedding calls.

    Example::

        retriever = QdrantRetriever(
            qdrant_store=qdrant,
            collection_name="patient_data",
            embedding_fn=embed_text,
        )
        results = await retriever.retrieve(
            RetrievalRequest(query="high carb meals", patient_ids=["p123"], data_types=["meal"])
        )
    """

    name: str = "qdrant"

    def __init__(
        self,
        *,
        qdrant_store: QdrantStore,
        collection_name: str = "patient_data",
        embedding_fn: Any = None,
        embedding_cache: EmbeddingCache | None = None,
    ) -> None:
        self._store = qdrant_store
        self._collection = collection_name
        self._embed_fn = embedding_fn
        self._embed_cache = embedding_cache

    async def retrieve(self, request: RetrievalRequest) -> list[RetrievalResult]:
        """Execute semantic search against Qdrant.

        Builds a filter from the request, embeds the query, and searches.
        """
        if self._embed_fn is None:
            raise RuntimeError("QdrantRetriever requires an embedding_fn.")

        # Embed query (with cache if available)
        query_vector: list[float]
        if self._embed_cache:
            cached = self._embed_cache.get(request.query)
            if cached:
                query_vector = cached
            else:
                query_vector = await self._embed_fn(request.query)
                self._embed_cache.set(request.query, query_vector)
        else:
            query_vector = await self._embed_fn(request.query)

        # Build Qdrant filter
        must_conditions: list[dict[str, Any]] = []

        if request.patient_ids:
            must_conditions.append({
                "key": "patient_id",
                "match": {"any": request.patient_ids},
            })

        if request.data_types:
            must_conditions.append({
                "key": "data_type",
                "match": {"any": request.data_types},
            })

        if request.date_start:
            must_conditions.append({
                "key": "date",
                "range": {"gte": request.date_start},
            })

        if request.date_end:
            must_conditions.append({
                "key": "date",
                "range": {"lt": request.date_end},
            })

        # Pass-through any extra filters
        for key, value in request.filters.items():
            if isinstance(value, dict) and "range" in value:
                must_conditions.append({"key": key, "range": value["range"]})
            else:
                must_conditions.append({"key": key, "match": {"value": value}})

        search_filter = {"must": must_conditions} if must_conditions else None

        # Execute search
        client = self._store.get_client()
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
