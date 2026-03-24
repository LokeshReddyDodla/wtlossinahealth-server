"""
Patient Summary Retriever — fetches daily aggregated health summaries.

Covers sleep, vitals, glucose overview, meal totals, and activity — data
that lives in the `patient_summaries` MongoDB collection. This is the
third retriever source alongside Qdrant (semantic) and Mongo reports (exact).

When multiple days are in scope, aggregates them into a single summary
with averages and totals.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import TYPE_CHECKING, Any

from .base import RetrievalRequest, RetrievalResult

if TYPE_CHECKING:
    from lib.core.mongo_store import MongoStore

logger = logging.getLogger(__name__)

COLLECTION = "patient_summaries"

# Data types that should trigger patient summary retrieval
_SUMMARY_TRIGGERS = {
    "sleep", "sleep_report", "vitals", "patient_summary",
    "cgm_summary_stats", "cgm_range_stats", "meal", "fitness_overview",
}


class PatientSummaryRetriever:
    """Fetches daily patient summaries from MongoDB.

    Handles single-day lookups and multi-day aggregation (averages, totals).
    Covers sleep, vitals, glucose, meals, and activity.
    """

    name: str = "patient_summary"

    def __init__(self, mongo_store: MongoStore) -> None:
        self._mongo = mongo_store

    async def retrieve(self, request: RetrievalRequest) -> list[RetrievalResult]:
        """Fetch and optionally aggregate patient summaries."""
        if not request.patient_ids:
            return []

        # Only trigger for relevant data types (or if no types specified — broad query)
        if request.data_types and not _SUMMARY_TRIGGERS.intersection(request.data_types):
            return []

        results: list[RetrievalResult] = []
        for patient_id in request.patient_ids:
            docs = await self._fetch_summaries(patient_id, request)
            if not docs:
                continue

            if len(docs) == 1:
                payload = self._normalize_single(docs[0])
            else:
                payload = self._aggregate(docs)

            results.append(RetrievalResult(
                payload=payload,
                source="patient_summary",
                score=None,
                data_type="patient_summary",
            ))

        logger.debug("Patient summary fetch: %d results for %d patients", len(results), len(request.patient_ids))
        return results

    async def _fetch_summaries(
        self, patient_id: str, request: RetrievalRequest,
    ) -> list[dict]:
        """Fetch raw summary docs from MongoDB."""
        query: dict[str, Any] = {
            "patient_id": patient_id,
            "metadata.report_type": "daily",
        }

        # Date filtering
        if request.date_start or request.date_end:
            date_filter: dict[str, str] = {}
            if request.date_start:
                date_filter["$gte"] = request.date_start[:10]
            if request.date_end:
                date_filter["$lte"] = request.date_end[:10] + "T23:59:59"
            query["metadata.date_range.start"] = date_filter
        else:
            # Default: last 7 days
            week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
            query["metadata.date_range.start"] = {"$gte": week_ago}

        try:
            docs = await self._mongo.find_many(COLLECTION, query, projection={"_id": 0})
            return sorted(docs, key=lambda d: d.get("metadata", {}).get("date_range", {}).get("start", ""))
        except Exception as exc:
            logger.warning("Patient summary fetch failed for %s: %s", patient_id, exc)
            return []

    @staticmethod
    def _normalize_single(doc: dict) -> dict[str, Any]:
        """Normalize a single daily summary."""
        summary_date = doc.get("metadata", {}).get("date_range", {}).get("start", "")[:10]
        return {
            "data_type": "patient_summary",
            "patient_id": doc.get("patient_id"),
            "summary_date": summary_date,
            "summary_days": 1,
            "data_presence": doc.get("data_presence", {}),
            "glucose": doc.get("glucose"),
            "meals": doc.get("meals"),
            "activity": doc.get("activity"),
            "sleep": doc.get("sleep"),
            "vitals": doc.get("vitals"),
            "flags": doc.get("flags", []),
            "source": "patient_summary",
        }

    @staticmethod
    def _aggregate(docs: list[dict]) -> dict[str, Any]:
        """Aggregate multiple daily summaries into one."""
        def avg(values: list[float]) -> float | None:
            return round(mean(values), 2) if values else None

        def nums(items: list[dict], key: str) -> list[float]:
            return [float(item[key]) for item in items if isinstance(item.get(key), (int, float))]

        glucose_docs = [d.get("glucose") or {} for d in docs if d.get("glucose")]
        meal_docs = [d.get("meals") or {} for d in docs if d.get("meals")]
        activity_docs = [d.get("activity") or {} for d in docs if d.get("activity")]
        sleep_docs = [d.get("sleep") or {} for d in docs if d.get("sleep")]
        vitals_docs = [d.get("vitals") or {} for d in docs if d.get("vitals")]

        glucose = None
        if glucose_docs:
            glucose = {
                "avg_mgdl": avg(nums(glucose_docs, "avg_mgdl")),
                "tir_pct": avg(nums(glucose_docs, "tir_pct")),
                "hyper_event_count": int(sum(nums(glucose_docs, "hyper_event_count"))),
                "hypo_event_count": int(sum(nums(glucose_docs, "hypo_event_count"))),
            }

        meals = None
        if meal_docs:
            totals = [d.get("nutrition_totals") or {} for d in meal_docs]
            meals = {
                "meal_count": int(sum(nums(meal_docs, "meal_count"))),
                "avg_daily_calories": avg(nums(totals, "calories")),
                "avg_daily_protein_g": avg(nums(totals, "protein_g")),
                "avg_daily_carbs_g": avg(nums(totals, "carbs_g")),
                "avg_daily_fat_g": avg(nums(totals, "fat_g")),
            }

        activity = None
        if activity_docs:
            activity = {
                "total_steps": int(sum(nums(activity_docs, "steps"))),
                "avg_daily_steps": avg(nums(activity_docs, "steps")),
                "avg_active_minutes": avg(nums(activity_docs, "active_minutes")),
            }

        sleep = None
        if sleep_docs:
            sleep = {
                "avg_duration_hours": avg(nums(sleep_docs, "duration_hours")),
                "avg_efficiency_pct": avg(nums(sleep_docs, "efficiency_pct")),
                "sleep_quality": sleep_docs[-1].get("sleep_quality"),
            }

        vitals = None
        if vitals_docs:
            vitals = {
                "weight_kg": avg(nums(vitals_docs, "weight_kg")),
                "heart_rate_avg": avg(nums(vitals_docs, "heart_rate_avg")),
                "spo2_avg": avg(nums(vitals_docs, "spo2_avg")),
                "a1c_latest": vitals_docs[-1].get("a1c_latest"),
                "blood_pressure_avg": vitals_docs[-1].get("blood_pressure_avg"),
            }

        # Aggregate flags
        flags: list[str] = []
        for d in docs:
            for f in d.get("flags", []) or []:
                if f not in flags:
                    flags.append(f)

        return {
            "data_type": "patient_summary",
            "patient_id": docs[0].get("patient_id"),
            "summary_days": len(docs),
            "data_presence": {
                k: any(bool((d.get("data_presence") or {}).get(k)) for d in docs)
                for k in set().union(*(d.get("data_presence", {}).keys() for d in docs))
            },
            "glucose": glucose,
            "meals": meals,
            "activity": activity,
            "sleep": sleep,
            "vitals": vitals,
            "flags": flags,
            "source": "patient_summary",
        }
