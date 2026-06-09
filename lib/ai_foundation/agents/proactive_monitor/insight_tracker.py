"""
Insight Tracker — deduplication + escalation for proactive monitor insights.

Tracks sent insights per patient per category in MongoDB collection
``ai_proactive_insights``.  Before sending a notification the caller asks
:pymethod:`should_send` which enforces:

* **24-hour dedup** — same category won't fire again within 24 h.
* **Escalation** — if the same pattern persists for 3+ consecutive days the
  severity is bumped to ``attention``; 5+ days bumps to ``warning``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.core.mongo_store import MongoStore

logger = logging.getLogger(__name__)

COLLECTION_NAME = "ai_proactive_insights"

# Escalation thresholds (consecutive days)
_ESCALATE_ATTENTION_DAYS = 3
_ESCALATE_WARNING_DAYS = 5

# Dedup window
_DEDUP_HOURS = 24

# Consecutive-day tolerance — if the previous insight was sent less than
# 48 hours ago we still count it as consecutive.
_CONSECUTIVE_TOLERANCE_HOURS = 48

# TTL — auto-delete records older than 30 days
_TTL_SECONDS = 30 * 24 * 3600


class InsightTracker:
    """Tracks sent insights to prevent spam and enable escalation."""

    def __init__(self, mongo_store: MongoStore) -> None:
        self._collection = mongo_store.get_collection(COLLECTION_NAME)
        self._indexes_ensured = False

    # -- Public API ---------------------------------------------------------

    async def should_send(
        self,
        patient_id: str,
        category: str,
    ) -> tuple[bool, str, int]:
        """Check whether an insight should be delivered.

        Returns ``(should_send, escalated_severity, consecutive_days)`` where
        *escalated_severity* reflects how long the pattern has persisted and
        *consecutive_days* is the streak count (pass to :meth:`record` to
        avoid a redundant MongoDB query).
        """
        await self._maybe_ensure_indexes()

        last = await self._collection.find_one(
            {"patient_id": patient_id, "category": category},
            sort=[("created_at", -1)],
        )

        if not last:
            return True, "info", 1  # First time — send as INFO

        now = datetime.now(timezone.utc)
        last_sent: datetime = last.get("created_at", now)
        if last_sent.tzinfo is None:
            last_sent = last_sent.replace(tzinfo=timezone.utc)
        hours_since = (now - last_sent).total_seconds() / 3600

        # Don't repeat within 24 hours
        if hours_since < _DEDUP_HOURS:
            return False, last.get("severity", "info"), last.get("consecutive_days", 0)

        # Escalation: count consecutive days
        if hours_since >= _CONSECUTIVE_TOLERANCE_HOURS:
            consecutive_days = 1
        else:
            consecutive_days = last.get("consecutive_days", 0) + 1
        if consecutive_days >= _ESCALATE_WARNING_DAYS:
            severity = "warning"
        elif consecutive_days >= _ESCALATE_ATTENTION_DAYS:
            severity = "attention"
        else:
            severity = "info"

        return True, severity, consecutive_days

    async def record(
        self,
        patient_id: str,
        category: str,
        severity: str,
        message: str,
        *,
        insight_id: str | None = None,
        title: str | None = None,
        suggested_query: str | None = None,
        trace_id: str | None = None,
        trigger: str | None = None,
        consecutive_days: int | None = None,
    ) -> None:
        """Record that an insight was sent.

        Args:
            consecutive_days: If provided (from :meth:`should_send`), skips
                the MongoDB query to re-derive the streak count.
        """
        await self._maybe_ensure_indexes()

        now = datetime.now(timezone.utc)

        # Use caller-provided value when available to avoid redundant query
        if consecutive_days is not None:
            consecutive = consecutive_days
        else:
            # Determine consecutive-day count
            last = await self._collection.find_one(
                {"patient_id": patient_id, "category": category},
                sort=[("created_at", -1)],
            )

            consecutive = 1
            if last:
                last_sent: datetime = last.get("created_at", now)
                if last_sent.tzinfo is None:
                    last_sent = last_sent.replace(tzinfo=timezone.utc)
                hours_since = (now - last_sent).total_seconds() / 3600
                if hours_since < _CONSECUTIVE_TOLERANCE_HOURS:
                    consecutive = last.get("consecutive_days", 0) + 1

        doc: dict = {
            "patient_id": patient_id,
            "category": category,
            "severity": severity,
            "message": message,
            "consecutive_days": consecutive,
            "created_at": now,
        }
        if insight_id:
            doc["insight_id"] = insight_id
        if title:
            doc["title"] = title
        if suggested_query:
            doc["suggested_query"] = suggested_query
        if trace_id:
            doc["trace_id"] = trace_id
        doc["trigger"] = trigger or "cron"

        await self._collection.insert_one(doc)

    async def get_by_insight_id(self, insight_id: str) -> dict | None:
        """Look up a recorded proactive insight by its public insight id."""
        await self._maybe_ensure_indexes()
        doc = await self._collection.find_one({"insight_id": insight_id})
        if doc and "_id" in doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def get_history(
        self,
        patient_id: str,
        limit: int = 20,
        *,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[dict]:
        """Get recent insight history for a patient (newest first).

        Excludes dedup-only records (those without an insight_id) that are
        created by daily briefs to block afternoon/evening duplicate topics.
        """
        await self._maybe_ensure_indexes()
        query: dict = {"patient_id": patient_id, "insight_id": {"$exists": True}}
        if from_date is not None or to_date is not None:
            range_clause: dict = {}
            if from_date is not None:
                range_clause["$gte"] = (
                    from_date if from_date.tzinfo else from_date.replace(tzinfo=timezone.utc)
                )
            if to_date is not None:
                range_clause["$lte"] = (
                    to_date if to_date.tzinfo else to_date.replace(tzinfo=timezone.utc)
                )
            query["created_at"] = range_clause
        cursor = self._collection.find(
            query,
            sort=[("created_at", -1)],
            limit=limit,
        )
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    async def get_insights_for_patients(
        self,
        patient_ids: list[str],
        *,
        since_days: int = 7,
        limit_per_patient: int = 5,
    ) -> dict[str, list[dict]]:
        """Get recent insights for multiple patients in a single query.

        Returns dict mapping patient_id → list of recent insights (newest first).
        Patients with no insights are not included in the result.
        """
        if not patient_ids:
            return {}

        await self._maybe_ensure_indexes()
        since = datetime.now(timezone.utc) - timedelta(days=since_days)

        # Use aggregation pipeline for fair per-patient limiting (avoids data skew)
        pipeline = [
            {"$match": {"patient_id": {"$in": patient_ids}, "created_at": {"$gte": since}, "insight_id": {"$exists": True}}},
            {"$sort": {"created_at": -1}},
            {"$group": {
                "_id": "$patient_id",
                "docs": {"$push": "$$ROOT"},
            }},
            {"$project": {
                "docs": {"$slice": ["$docs", limit_per_patient]},
            }},
        ]

        by_patient: dict[str, list[dict]] = {}
        async for group in self._collection.aggregate(pipeline):
            pid = group["_id"]
            by_patient[pid] = []
            for doc in group["docs"]:
                doc["_id"] = str(doc["_id"])
                by_patient[pid].append(doc)

        return by_patient

    async def ensure_indexes(self) -> None:
        """Create indexes for efficient lookups. Safe to call multiple times."""
        await self._collection.create_index(
            [("patient_id", 1), ("category", 1), ("created_at", -1)],
            name="insight_patient_category_idx",
        )
        await self._collection.create_index(
            "created_at",
            name="insight_ttl_idx",
            expireAfterSeconds=_TTL_SECONDS,
        )
        await self._collection.create_index(
            "insight_id",
            name="insight_id_idx",
        )
        self._indexes_ensured = True

    # -- Internal -----------------------------------------------------------

    async def _maybe_ensure_indexes(self) -> None:
        if not self._indexes_ensured:
            try:
                await self.ensure_indexes()
            except Exception:
                logger.debug("Index creation deferred — may not be connected yet")
                self._indexes_ensured = False
