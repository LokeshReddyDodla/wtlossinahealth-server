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
    ) -> tuple[bool, str]:
        """Check whether an insight should be delivered.

        Returns ``(should_send, escalated_severity)`` where
        *escalated_severity* reflects how long the pattern has persisted.
        """
        await self._maybe_ensure_indexes()

        last = await self._collection.find_one(
            {"patient_id": patient_id, "category": category},
            sort=[("created_at", -1)],
        )

        if not last:
            return True, "info"  # First time — send as INFO

        now = datetime.utcnow()
        last_sent: datetime = last.get("created_at", now)
        if last_sent.tzinfo is not None:
            last_sent = last_sent.replace(tzinfo=None)
        hours_since = (now - last_sent).total_seconds() / 3600

        # Don't repeat within 24 hours
        if hours_since < _DEDUP_HOURS:
            return False, last.get("severity", "info")

        # Escalation: count consecutive days
        consecutive_days = last.get("consecutive_days", 0) + 1
        if consecutive_days >= _ESCALATE_WARNING_DAYS:
            severity = "warning"
        elif consecutive_days >= _ESCALATE_ATTENTION_DAYS:
            severity = "attention"
        else:
            severity = "info"

        return True, severity

    async def record(
        self,
        patient_id: str,
        category: str,
        severity: str,
        message: str,
    ) -> None:
        """Record that an insight was sent."""
        await self._maybe_ensure_indexes()

        now = datetime.utcnow()

        # Determine consecutive-day count
        last = await self._collection.find_one(
            {"patient_id": patient_id, "category": category},
            sort=[("created_at", -1)],
        )

        consecutive = 1
        if last:
            last_sent: datetime = last.get("created_at", now)
            if last_sent.tzinfo is not None:
                last_sent = last_sent.replace(tzinfo=None)
            hours_since = (now - last_sent).total_seconds() / 3600
            if hours_since < _CONSECUTIVE_TOLERANCE_HOURS:
                consecutive = last.get("consecutive_days", 0) + 1

        await self._collection.insert_one({
            "patient_id": patient_id,
            "category": category,
            "severity": severity,
            "message": message,
            "consecutive_days": consecutive,
            "created_at": now,
        })

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
        self._indexes_ensured = True

    # -- Internal -----------------------------------------------------------

    async def _maybe_ensure_indexes(self) -> None:
        if not self._indexes_ensured:
            try:
                await self.ensure_indexes()
            except Exception:
                logger.debug("Index creation deferred — may not be connected yet")
                self._indexes_ensured = True  # don't retry every call
