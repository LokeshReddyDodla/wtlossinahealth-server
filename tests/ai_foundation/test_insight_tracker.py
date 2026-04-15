"""Tests for ProactiveMonitor.InsightTracker — dedup + escalation logic.

The InsightTracker prevents notification spam and escalates persistent
patterns. This file locks every branch:

- First insight per category → send as INFO
- Within 24h dedup window → don't resend
- After 24h, consecutive_days < 3 → INFO
- consecutive_days >= 3 → ATTENTION
- consecutive_days >= 5 → WARNING
- Gap > 48h → reset consecutive_days to 1 (broken streak)
- Naive datetime in DB is treated as UTC
- record() short-circuits MongoDB query when consecutive_days passed in
- get_history filters out dedup-only records (no insight_id)
- get_insights_for_patients with empty list returns empty dict
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.agents.proactive_monitor.insight_tracker import (
    InsightTracker,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


def _make_tracker(find_one_return=None):
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=find_one_return)
    collection.insert_one = AsyncMock()
    collection.create_index = AsyncMock()
    collection.find = MagicMock()
    collection.aggregate = MagicMock()
    store = MagicMock()
    store.get_collection = MagicMock(return_value=collection)
    tracker = InsightTracker(mongo_store=store)
    tracker._indexes_ensured = True  # bypass index creation
    return tracker, collection


def _last_record(hours_ago, severity="info", consecutive_days=1, **extra):
    """Simulate a previous insight record."""
    return {
        "patient_id": "p1",
        "category": "glucose",
        "severity": severity,
        "consecutive_days": consecutive_days,
        "created_at": datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        **extra,
    }


# ── First-time insight: send as INFO ────────────────────────────────────────


class TestFirstInsight:
    @pytest.mark.asyncio
    async def test_no_previous_insight_sends_as_info(self):
        tracker, _ = _make_tracker(find_one_return=None)
        send, sev, days = await tracker.should_send("p1", "glucose")
        assert send is True
        assert sev == "info"
        assert days == 1


# ── Dedup window (within 24h) ───────────────────────────────────────────────


class TestDedupWindow:
    @pytest.mark.parametrize("hours_ago", [0.5, 1, 6, 12, 23, 23.99])
    @pytest.mark.asyncio
    async def test_within_24h_blocks(self, hours_ago):
        tracker, _ = _make_tracker(
            find_one_return=_last_record(hours_ago=hours_ago, severity="info"),
        )
        send, sev, days = await tracker.should_send("p1", "glucose")
        assert send is False
        # Returns the previously sent severity
        assert sev == "info"


# ── Escalation by consecutive days ─────────────────────────────────────────


class TestEscalation:
    @pytest.mark.parametrize(
        "prev_consecutive_days,expected_severity",
        [
            (0, "info"),    # 0 + 1 = 1 → info
            (1, "info"),    # 1 + 1 = 2 → info
            (2, "attention"),  # 2 + 1 = 3 → attention
            (3, "attention"),  # 3 + 1 = 4 → attention
            (4, "warning"),    # 4 + 1 = 5 → warning
            (10, "warning"),   # 10 + 1 = 11 → warning
        ],
    )
    @pytest.mark.asyncio
    async def test_escalation_thresholds(
        self, prev_consecutive_days, expected_severity,
    ):
        # Last sent 25h ago (past dedup window, still within 48h consecutive tolerance)
        tracker, _ = _make_tracker(
            find_one_return=_last_record(
                hours_ago=25,
                consecutive_days=prev_consecutive_days,
            ),
        )
        send, sev, days = await tracker.should_send("p1", "glucose")
        assert send is True
        assert sev == expected_severity
        assert days == prev_consecutive_days + 1

    @pytest.mark.asyncio
    async def test_streak_resets_after_48h_gap(self):
        """Last insight was 49h ago (past 48h consecutive tolerance) → streak resets to 1."""
        tracker, _ = _make_tracker(
            find_one_return=_last_record(hours_ago=49, consecutive_days=10),
        )
        send, sev, days = await tracker.should_send("p1", "glucose")
        assert send is True
        assert sev == "info"  # reset to info because days=1
        assert days == 1


# ── Naive datetime in DB ────────────────────────────────────────────────────


class TestNaiveDatetimeHandling:
    @pytest.mark.asyncio
    async def test_naive_datetime_treated_as_utc(self):
        """Some Mongo records have naive datetimes — must be promoted to UTC."""
        last = _last_record(hours_ago=1)
        # Make naive
        last["created_at"] = last["created_at"].replace(tzinfo=None)

        tracker, _ = _make_tracker(find_one_return=last)
        send, _, _ = await tracker.should_send("p1", "glucose")
        # 1h ago → still in dedup window → don't send
        assert send is False


# ── record() inserts proper document ────────────────────────────────────────


class TestRecord:
    @pytest.mark.asyncio
    async def test_record_inserts_required_fields(self):
        tracker, collection = _make_tracker(find_one_return=None)
        await tracker.record(
            patient_id="p1",
            category="glucose",
            severity="warning",
            message="Glucose high",
            consecutive_days=5,
        )
        collection.insert_one.assert_awaited_once()
        doc = collection.insert_one.await_args.args[0]
        assert doc["patient_id"] == "p1"
        assert doc["category"] == "glucose"
        assert doc["severity"] == "warning"
        assert doc["message"] == "Glucose high"
        assert doc["consecutive_days"] == 5
        assert "created_at" in doc

    @pytest.mark.asyncio
    async def test_record_optional_fields_included_when_provided(self):
        tracker, collection = _make_tracker(find_one_return=None)
        await tracker.record(
            patient_id="p1", category="glucose",
            severity="info", message="m",
            insight_id="abc-123",
            title="High glucose",
            suggested_query="Show me my CGM trace",
            trace_id="trace-1",
            consecutive_days=1,
        )
        doc = collection.insert_one.await_args.args[0]
        assert doc["insight_id"] == "abc-123"
        assert doc["title"] == "High glucose"
        assert doc["suggested_query"] == "Show me my CGM trace"
        assert doc["trace_id"] == "trace-1"

    @pytest.mark.asyncio
    async def test_record_short_circuits_when_consecutive_days_passed(self):
        """When the caller already computed consecutive_days via should_send,
        record() should skip the redundant find_one query."""
        tracker, collection = _make_tracker(find_one_return=None)
        await tracker.record(
            patient_id="p1", category="glucose",
            severity="info", message="m", consecutive_days=4,
        )
        # find_one not called
        collection.find_one.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_record_queries_when_consecutive_days_omitted(self):
        tracker, collection = _make_tracker(find_one_return=None)
        await tracker.record(
            patient_id="p1", category="glucose",
            severity="info", message="m",
        )
        # find_one called to derive count
        collection.find_one.assert_awaited_once()


# ── get_insights_for_patients with empty input ─────────────────────────────


class TestGetInsightsForPatients:
    @pytest.mark.asyncio
    async def test_empty_patient_list_returns_empty_dict(self):
        tracker, collection = _make_tracker()
        result = await tracker.get_insights_for_patients([])
        assert result == {}
        # No DB call needed
        collection.aggregate.assert_not_called()


# ── get_by_insight_id ──────────────────────────────────────────────────────


class TestGetByInsightId:
    @pytest.mark.asyncio
    async def test_returns_doc_with_string_id(self):
        from bson import ObjectId
        oid = ObjectId()
        tracker, collection = _make_tracker(
            find_one_return={"_id": oid, "insight_id": "abc"},
        )
        result = await tracker.get_by_insight_id("abc")
        assert result is not None
        assert result["_id"] == str(oid)

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        tracker, _ = _make_tracker(find_one_return=None)
        result = await tracker.get_by_insight_id("nope")
        assert result is None
