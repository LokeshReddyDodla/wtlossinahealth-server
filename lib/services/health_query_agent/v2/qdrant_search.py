from __future__ import annotations

import logging
from typing import Optional

try:
    from decouple import config
except ImportError:  # pragma: no cover - test fallback
    def config(*_args, default=None, **_kwargs):
        return default

from lib.core.qdrant_store import QdrantStore
from lib.utils.vector_utils import embed_text

from .contracts import QueryIntent
from .filter_builder import FilterBuilder


logger = logging.getLogger(__name__)

QDRANT_COLLECTION = config("QDRANT_COLLECTION", default="patient_data")


async def search_qdrant(
    query: str,
    intent: QueryIntent,
    qdrant_store: QdrantStore,
    patient_ids: Optional[list[str]] = None,
    limit: int = 24,
) -> tuple[list, Optional[float]]:
    qdrant_filter = FilterBuilder.build(intent, patient_ids)
    logger.info("Built Qdrant filter: %s", qdrant_filter)

    query_embedding = await embed_text(query)

    async with qdrant_store.get_client() as client:
        results = await client.search(
            collection_name=QDRANT_COLLECTION,
            query_vector=query_embedding,
            query_filter=qdrant_filter,
            limit=limit,
        )

    search_confidence = results[0].score if results else None
    return results, search_confidence
