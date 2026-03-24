"""
MongoDB Report Retriever — fetches structured daily health reports.

Retrieves deterministic reports (meal, CGM, fitness, sleep) from MongoDB
collections. This is the "exact fetch" path — when the user asks about a
specific date or date range, this retriever provides precise structured data.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .base import RetrievalRequest, RetrievalResult

if TYPE_CHECKING:
    from lib.core.mongo_store import MongoStore

logger = logging.getLogger(__name__)

# Mapping from data_type categories to MongoDB collection names
_DATA_TYPE_COLLECTIONS: dict[str, str] = {
    "meal": "meal_reports",
    "cgm": "cgm_reports",
    "cgm_range_stats": "cgm_reports",
    "cgm_summary_stats": "cgm_reports",
    "fitness": "fitness_reports",
    "fitness_overview": "fitness_reports",
    "sleep": "sleep_reports",
}


class MongoReportRetriever:
    """Fetches structured daily reports from MongoDB.

    Determines which collections to query based on the ``data_types``
    in the retrieval request, then fetches reports for the given
    patient(s) and date range.

    Example::

        retriever = MongoReportRetriever(mongo_store)
        results = await retriever.retrieve(
            RetrievalRequest(
                query="meals yesterday",
                patient_ids=["p123"],
                data_types=["meal"],
                date_start="2026-03-23",
                date_end="2026-03-24",
            )
        )
    """

    name: str = "mongo_report"

    def __init__(self, mongo_store: MongoStore) -> None:
        self._mongo = mongo_store

    async def retrieve(self, request: RetrievalRequest) -> list[RetrievalResult]:
        """Fetch reports matching the request criteria."""
        # Determine which collections to query
        collections = self._resolve_collections(request.data_types)
        if not collections:
            # Default to all report collections if no data_types specified
            collections = list(set(_DATA_TYPE_COLLECTIONS.values()))

        results: list[RetrievalResult] = []

        for collection_name in collections:
            query = self._build_query(request)
            try:
                collection = self._mongo.get_collection(collection_name)
                cursor = collection.find(
                    query,
                    {"_id": 0},
                ).sort("date", -1).limit(request.limit)

                docs = await cursor.to_list(length=request.limit)
                for doc in docs:
                    results.append(
                        RetrievalResult(
                            payload=doc,
                            source=f"mongo:{collection_name}",
                            score=None,  # exact match, no relevance score
                            data_type=doc.get("data_type", collection_name.replace("_reports", "")),
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "MongoReportRetriever failed for %s: %s", collection_name, exc
                )

        logger.debug("Mongo report fetch: %d results from %s", len(results), collections)
        return results

    def _resolve_collections(self, data_types: list[str]) -> list[str]:
        """Map data_type names to MongoDB collection names."""
        collections: set[str] = set()
        for dt in data_types:
            # Direct mapping
            if dt in _DATA_TYPE_COLLECTIONS:
                collections.add(_DATA_TYPE_COLLECTIONS[dt])
            else:
                # Try prefix matching (e.g., "cgm_range_stats" → "cgm")
                prefix = dt.split("_")[0]
                if prefix in _DATA_TYPE_COLLECTIONS:
                    collections.add(_DATA_TYPE_COLLECTIONS[prefix])
        return list(collections)

    def _build_query(self, request: RetrievalRequest) -> dict[str, Any]:
        """Build a MongoDB query from the retrieval request."""
        query: dict[str, Any] = {}

        if request.patient_ids:
            if len(request.patient_ids) == 1:
                query["patient_id"] = request.patient_ids[0]
            else:
                query["patient_id"] = {"$in": request.patient_ids}

        date_filter: dict[str, str] = {}
        if request.date_start:
            date_filter["$gte"] = request.date_start
        if request.date_end:
            date_filter["$lt"] = request.date_end
        if date_filter:
            query["date"] = date_filter

        return query
