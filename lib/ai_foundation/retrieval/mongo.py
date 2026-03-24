"""
MongoDB Report Retriever — fetches structured daily health reports.

Retrieves deterministic reports (meal, CGM, fitness, sleep) from MongoDB
collections. This is the "exact fetch" path — when the user asks about a
specific date or date range, this retriever provides precise structured data.

Uses the same query patterns and normalization as the existing
MongoReportFetcher from health_query_agent/v2, but wrapped in the
standard Retriever interface.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .base import RetrievalRequest, RetrievalResult

if TYPE_CHECKING:
    from lib.core.mongo_store import MongoStore

logger = logging.getLogger(__name__)

# Domain → MongoDB collection mapping
_DOMAIN_COLLECTIONS: dict[str, str] = {
    "meal": "meal_reports",
    "cgm": "cgm_reports",
    "cgm_range_stats": "cgm_reports",
    "cgm_summary_stats": "cgm_reports",
    "hyper_stats": "cgm_reports",
    "hypo_stats": "cgm_reports",
    "rapid_spike_stats": "cgm_reports",
    "rapid_drop_stats": "cgm_reports",
    "fitness": "fitness_reports",
    "fitness_overview": "fitness_reports",
    "fitness_activity_distribution": "fitness_reports",
    "sleep": "sleep_reports",
}


class MongoReportRetriever:
    """Fetches structured daily reports from MongoDB.

    Determines which collections to query based on ``data_types`` in the
    request, then fetches and normalizes reports into standard payloads.

    Args:
        mongo_store: The ``MongoStore`` instance from ``lib/core``.
    """

    name: str = "mongo_report"

    def __init__(self, mongo_store: MongoStore) -> None:
        self._mongo = mongo_store

    async def retrieve(self, request: RetrievalRequest) -> list[RetrievalResult]:
        """Fetch reports matching the request criteria."""
        collections = self._resolve_collections(request.data_types)
        if not collections:
            return []

        results: list[RetrievalResult] = []

        for collection_name in collections:
            query = self._build_query(request)
            if not query:
                continue

            try:
                docs = await self._mongo.find_many(
                    collection_name,
                    query,
                    projection={"_id": 0},
                )

                # Cap results
                docs = docs[:request.limit]

                normalized = self._normalize(collection_name, docs)
                for payload in normalized:
                    results.append(RetrievalResult(
                        payload=payload,
                        source=f"mongo:{collection_name}",
                        score=None,
                        data_type=payload.get("data_type", "unknown"),
                    ))
            except Exception as exc:
                logger.warning("MongoReportRetriever failed for %s: %s", collection_name, exc)

        logger.debug("Mongo report fetch: %d results from %s", len(results), list(collections))
        return results

    # -- Collection resolution ----------------------------------------------

    @staticmethod
    def _resolve_collections(data_types: list[str]) -> set[str]:
        """Map data_type names to MongoDB collection names."""
        collections: set[str] = set()
        for dt in data_types:
            if dt in _DOMAIN_COLLECTIONS:
                collections.add(_DOMAIN_COLLECTIONS[dt])
            else:
                prefix = dt.split("_")[0]
                if prefix in _DOMAIN_COLLECTIONS:
                    collections.add(_DOMAIN_COLLECTIONS[prefix])
        return collections

    # -- Query building -----------------------------------------------------

    @staticmethod
    def _build_query(request: RetrievalRequest) -> dict[str, Any] | None:
        """Build MongoDB query from the retrieval request."""
        query: dict[str, Any] = {}

        if request.patient_ids:
            if len(request.patient_ids) == 1:
                query["patient_id"] = request.patient_ids[0]
            else:
                query["patient_id"] = {"$in": request.patient_ids}
        else:
            return None  # no patient = no query

        # Date filtering
        if request.date_start or request.date_end:
            # Try both "date" field (meal reports) and metadata date range (CGM, fitness, sleep)
            date_conditions: list[dict] = []

            # Direct date field (meal reports use this)
            date_filter: dict[str, str] = {}
            if request.date_start:
                date_filter["$gte"] = request.date_start[:10]
            if request.date_end:
                date_filter["$lte"] = request.date_end[:10]
            if date_filter:
                date_conditions.append({"date": date_filter})

            # Metadata date range (CGM, fitness, sleep reports use this)
            meta_filter: dict[str, Any] = {}
            if request.date_start:
                meta_filter["metadata.date_range.start"] = {"$gte": request.date_start}
            if request.date_end:
                meta_filter["metadata.date_range.end"] = {"$lte": request.date_end}
            if meta_filter:
                date_conditions.append(meta_filter)

            if len(date_conditions) > 1:
                query["$or"] = date_conditions
            elif date_conditions:
                query.update(date_conditions[0])

        return query

    # -- Normalization ------------------------------------------------------

    def _normalize(self, collection_name: str, docs: list[dict]) -> list[dict]:
        """Normalize raw MongoDB documents into standard payloads."""
        if collection_name == "meal_reports":
            return self._normalize_meal_reports(docs)
        if collection_name == "cgm_reports":
            return self._normalize_cgm_reports(docs)
        if collection_name == "fitness_reports":
            return self._normalize_fitness_reports(docs)
        if collection_name == "sleep_reports":
            return self._normalize_sleep_reports(docs)
        # Unknown collection — return raw docs with source tag
        return [{"data_type": "unknown", "source": "mongo_report", **doc} for doc in docs]

    @staticmethod
    def _normalize_meal_reports(docs: list[dict]) -> list[dict]:
        """Extract individual meals from daily meal reports."""
        payloads: list[dict] = []
        for doc in docs:
            report_date = doc.get("date") or (
                doc.get("metadata", {}).get("date_range", {}).get("start", "")[:10]
            )
            meals = doc.get("meals") or []
            for meal in meals:
                payloads.append({
                    "data_type": "meal",
                    "date": report_date,
                    "meal_type": meal.get("meal_type") or meal.get("type"),
                    "meal_name": meal.get("meal_name") or meal.get("name"),
                    "time": meal.get("time"),
                    "nutrition": meal.get("nutrition") or meal.get("macros") or {},
                    "source": "mongo_report",
                })
        return payloads

    @staticmethod
    def _normalize_cgm_reports(docs: list[dict]) -> list[dict]:
        """Extract CGM summary and range stats from daily CGM reports."""
        payloads: list[dict] = []
        for doc in docs:
            date_range = doc.get("metadata", {}).get("date_range", {})
            report_date = date_range.get("start", "")[:10]

            summary_stats = doc.get("cgm_summary_stats") or {}
            range_stats = doc.get("cgm_range_stats") or {}

            if summary_stats:
                payloads.append({
                    "data_type": "cgm_summary_stats",
                    "date": report_date,
                    "average_glucose_mgdl": summary_stats.get("average_glucose_mgdl"),
                    "gmi": summary_stats.get("gmi"),
                    "cv": summary_stats.get("cv"),
                    "source": "mongo_report",
                })
            if range_stats:
                payloads.append({
                    "data_type": "cgm_range_stats",
                    "date": report_date,
                    "in_target_70_180_percent": range_stats.get("in_target_70_180_percent"),
                    "below_70_percent": range_stats.get("below_70_percent"),
                    "above_180_percent": range_stats.get("above_180_percent"),
                    "source": "mongo_report",
                })
        return payloads

    @staticmethod
    def _normalize_fitness_reports(docs: list[dict]) -> list[dict]:
        """Extract fitness metrics from daily fitness reports."""
        payloads: list[dict] = []
        for doc in docs:
            peak = doc.get("peak_activity_time") or {}
            hour = peak.get("hour")
            try:
                peak_hour = int(str(hour).split(":")[0]) if hour is not None else None
            except Exception:
                peak_hour = None

            payloads.append({
                "data_type": "fitness_overview",
                "steps": doc.get("steps"),
                "active_duration": doc.get("active_duration"),
                "active_energy": doc.get("active_energy"),
                "peak_hour": peak_hour,
                "source": "mongo_report",
            })
        return payloads

    @staticmethod
    def _normalize_sleep_reports(docs: list[dict]) -> list[dict]:
        """Extract sleep metrics from daily sleep reports."""
        payloads: list[dict] = []
        for doc in docs:
            duration = doc.get("duration") or {}
            quality = doc.get("quality") or {}
            avg_minutes = (
                duration.get("per_day_average_duration")
                or duration.get("average_duration")
                or duration.get("total_duration")
            )
            payloads.append({
                "data_type": "sleep_report",
                "duration_hours": round(float(avg_minutes) / 60, 2) if isinstance(avg_minutes, (int, float)) else None,
                "efficiency_pct": quality.get("sleep_efficiency"),
                "sleep_quality": quality.get("sleep_quality"),
                "source": "mongo_report",
            })
        return payloads
