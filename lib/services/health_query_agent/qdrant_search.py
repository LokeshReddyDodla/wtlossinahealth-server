"""
Qdrant search operations for the health query agent.
"""

import logging
from typing import Optional

from decouple import config

from lib.core.qdrant_store import QdrantStore
from lib.utils.vector_utils import embed_text
from .filter_builder import FilterBuilder
from .schemas import QueryIntent


logger = logging.getLogger(__name__)

QDRANT_COLLECTION = config("QDRANT_COLLECTION", default="patient_data")


async def search_qdrant(
    query: str,
    intent: QueryIntent,
    qdrant_store: QdrantStore,
    patient_ids: Optional[list[str]] = None,
) -> tuple[list, Optional[float]]:
    # Build filters
    qdrant_filter = FilterBuilder.build(intent, patient_ids)

    logger.info(f"Built Qdrant filter: {qdrant_filter}")

    # Generate embedding for semantic search
    query_embedding = await embed_text(query)

    # Perform search directly with Qdrant
    results = []
    search_confidence = None
    async with qdrant_store.get_client() as client:
        results = await client.search(
            collection_name=QDRANT_COLLECTION,
            query_vector=query_embedding,
            query_filter=qdrant_filter,
            limit=999,
        )

    search_confidence = results[0].score if results else None
    return results, search_confidence
