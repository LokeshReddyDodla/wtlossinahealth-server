"""
Qdrant search operations for the health query agent.
"""
import logging
from typing import Optional

from lib.core.qdrant_store import QdrantStore
from lib.utils.vector_utils import embed_text
from microservices.health_query_agent.config import settings
from .filter_builder import FilterBuilder
from .schemas import QueryIntent
from qdrant_client.http.models import (
    Filter,
    FieldCondition,
    MatchValue,
    MatchAny,
    Condition,
)

logger = logging.getLogger(__name__)


def build_api_filter(
    patient_ids: Optional[list[str]] = None,
) -> Optional[Filter]:
    conditions: list[Condition] = []

    if patient_ids:
        # supports one or many patient IDs
        if len(patient_ids) == 1:
            conditions.append(
                FieldCondition(
                    key="patient_id",
                    match=MatchValue(value=patient_ids[0]),
                )
            )
        else:
            conditions.append(
                FieldCondition(key="patient_id", match=MatchAny(any=patient_ids))
            )

    return Filter(must=conditions) if conditions else None


def merge_filters(
    intent_filter: Optional[Filter], api_filter: Optional[Filter]
) -> Optional[Filter]:
    if intent_filter and api_filter:
        return Filter(
            must=(intent_filter.must or []) + (api_filter.must or []),  # type: ignore
            should=(intent_filter.should or []) + (api_filter.should or []),  # type: ignore
            must_not=(intent_filter.must_not or []) + (api_filter.must_not or []),  # type: ignore
        )
    return intent_filter or api_filter


async def search_qdrant(
    query: str,
    intent: QueryIntent,
    qdrant_store: QdrantStore,
    patient_ids: Optional[list[str]] = None,
) -> tuple[list, Optional[float]]:
    # Build filters
    intent_filter = FilterBuilder.build(intent)
    api_filter = build_api_filter(patient_ids=patient_ids)
    merged_filter = merge_filters(intent_filter, api_filter)

    logger.info(f"Built Qdrant filter: {merged_filter}")

    # Generate embedding for semantic search
    query_embedding = await embed_text(query)

    # Perform search directly with Qdrant
    results = []
    search_confidence = None
    async with qdrant_store.get_client() as client:
        results = await client.search(
            collection_name=settings.QDRANT_COLLECTION,
            query_vector=query_embedding,
            limit=100,
            query_filter=merged_filter,
        )

        if results and len(results) > 0:
            top_result = results[0]
            search_confidence = getattr(top_result, "score", None)
            logger.debug(
                f"Extracted search_confidence: {search_confidence} from {len(results)} results"
            )

    return results, search_confidence
