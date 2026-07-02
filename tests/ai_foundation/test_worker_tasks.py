"""Tests for the proactive-monitor worker task boundaries.

The agent logic is covered by test_proactive_monitor.py; these lock the
arq task wrappers — the untyped JSON boundary where bad input must become
a failed TaskResult, never a crash — and the scan-window filter.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from lib.workers.tasks.proactive_monitor.scan import _filter_by_scan_window


class TestFilterByScanWindow:
    def test_all_within_window(self):
        with patch(
            "lib.workers.tasks.proactive_monitor.scan.is_within_scan_window",
            return_value=True,
        ):
            eligible, skipped = _filter_by_scan_window(
                ["p1", "p2"], {"p1": "Asia/Kolkata", "p2": "America/New_York"},
            )
        assert eligible == ["p1", "p2"]
        assert skipped == 0

    def test_outside_window_skipped(self):
        def fake_window(tz):
            return tz == "Asia/Kolkata"

        with patch(
            "lib.workers.tasks.proactive_monitor.scan.is_within_scan_window",
            side_effect=fake_window,
        ):
            eligible, skipped = _filter_by_scan_window(
                ["p1", "p2", "p3"],
                {"p1": "Asia/Kolkata", "p2": "America/New_York", "p3": "Asia/Kolkata"},
            )
        assert eligible == ["p1", "p3"]
        assert skipped == 1

    def test_missing_timezone_uses_default(self):
        seen: list[str] = []

        with patch(
            "lib.workers.tasks.proactive_monitor.scan.is_within_scan_window",
            side_effect=lambda tz: seen.append(tz) or True,
        ):
            _filter_by_scan_window(["p1"], {})

        from lib.ai_foundation.agents.proactive_monitor.scheduling import DEFAULT_TIMEZONE
        assert seen == [DEFAULT_TIMEZONE]


class TestHandleProactiveEventBoundary:
    """Invalid input at the arq JSON boundary → failed TaskResult, no crash."""

    @pytest.mark.asyncio
    async def test_unknown_trigger_fails_cleanly(self):
        from lib.workers.tasks.proactive_monitor.event_scan import handle_proactive_event

        result = await handle_proactive_event(
            {"job_id": "test"}, "patient-1", "not_a_real_trigger", None,
        )
        assert result.success is False
        assert "Unknown trigger" in (result.error or "")

    @pytest.mark.asyncio
    async def test_invalid_anchor_fails_cleanly(self):
        from lib.ai_foundation.agents.proactive_monitor.contracts import EventTrigger
        from lib.workers.tasks.proactive_monitor.event_scan import handle_proactive_event

        result = await handle_proactive_event(
            {"job_id": "test"},
            "patient-1",
            EventTrigger.MEAL_LOGGED.value,
            {"wrong_field": "nope"},  # MealLoggedAnchor requires meal_id
        )
        assert result.success is False
