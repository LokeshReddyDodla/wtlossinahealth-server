"""Unit tests for streak logic — freeze, gaps, buddy streaks.

Uses the stub-loading pattern to avoid requiring sqlalchemy at import time.
Tests the actual process_streak logic by calling the method with a mocked session.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tests.test_gamification_unit_logic import _base_stubs, _load_module


MODULE_PATH = "lib/services/gamification/streak_service.py"
MODULE_NAME = "test_streak_service"


@pytest.fixture
def streak_module(monkeypatch):
    return _load_module(monkeypatch, MODULE_PATH, MODULE_NAME, _base_stubs())


def _make_profile(**overrides):
    defaults = dict(
        patient_id=uuid4(),
        current_streak=0,
        longest_streak=0,
        streak_freezes=1,
        streak_resets=0,
        last_active_date=None,
        streak_frozen_on=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_service(module):
    svc = object.__new__(module.StreakService)
    svc.postgres_store = MagicMock()
    return svc


class TestProcessStreak:
    @pytest.mark.asyncio
    async def test_first_active_day_sets_streak_to_1(self, streak_module):
        svc = _make_service(streak_module)
        profile = _make_profile()
        session = AsyncMock()

        svc._get_or_create_profile = AsyncMock(return_value=profile)
        svc._was_active = AsyncMock(return_value=True)

        result = await svc.process_streak(
            profile.patient_id, date(2026, 4, 3), postgres_session=session
        )

        assert result["action"] == "incremented"
        assert profile.current_streak == 1
        assert profile.last_active_date == date(2026, 4, 3)

    @pytest.mark.asyncio
    async def test_consecutive_day_increments(self, streak_module):
        svc = _make_service(streak_module)
        profile = _make_profile(
            last_active_date=date(2026, 4, 2), current_streak=5, longest_streak=5
        )
        session = AsyncMock()

        svc._get_or_create_profile = AsyncMock(return_value=profile)
        svc._was_active = AsyncMock(return_value=True)

        result = await svc.process_streak(
            profile.patient_id, date(2026, 4, 3), postgres_session=session
        )

        assert result["action"] == "incremented"
        assert profile.current_streak == 6
        assert profile.longest_streak == 6

    @pytest.mark.asyncio
    async def test_gap_resets_to_1(self, streak_module):
        svc = _make_service(streak_module)
        profile = _make_profile(
            last_active_date=date(2026, 4, 1), current_streak=5
        )
        session = AsyncMock()

        svc._get_or_create_profile = AsyncMock(return_value=profile)
        svc._was_active = AsyncMock(return_value=True)

        await svc.process_streak(
            profile.patient_id, date(2026, 4, 3), postgres_session=session
        )

        assert profile.current_streak == 1

    @pytest.mark.asyncio
    async def test_freeze_consumed_on_inactive_day(self, streak_module):
        svc = _make_service(streak_module)
        profile = _make_profile(
            last_active_date=date(2026, 4, 2), current_streak=7, streak_freezes=2
        )
        session = AsyncMock()

        svc._get_or_create_profile = AsyncMock(return_value=profile)
        svc._was_active = AsyncMock(return_value=False)

        result = await svc.process_streak(
            profile.patient_id, date(2026, 4, 3), postgres_session=session
        )

        assert result["action"] == "frozen"
        assert profile.current_streak == 7
        assert profile.streak_freezes == 1
        assert profile.streak_frozen_on == date(2026, 4, 3)

    @pytest.mark.asyncio
    async def test_no_freeze_breaks_streak(self, streak_module):
        svc = _make_service(streak_module)
        profile = _make_profile(
            last_active_date=date(2026, 4, 2), current_streak=5, streak_freezes=0
        )
        session = AsyncMock()

        svc._get_or_create_profile = AsyncMock(return_value=profile)
        svc._was_active = AsyncMock(return_value=False)

        result = await svc.process_streak(
            profile.patient_id, date(2026, 4, 3), postgres_session=session
        )

        assert result["action"] == "broken"
        assert profile.current_streak == 0
        assert profile.streak_resets == 1

    @pytest.mark.asyncio
    async def test_already_processed_skips(self, streak_module):
        svc = _make_service(streak_module)
        profile = _make_profile(
            last_active_date=date(2026, 4, 3), current_streak=5
        )
        session = AsyncMock()

        svc._get_or_create_profile = AsyncMock(return_value=profile)

        result = await svc.process_streak(
            profile.patient_id, date(2026, 4, 3), postgres_session=session
        )

        assert result["action"] == "already_processed"

    @pytest.mark.asyncio
    async def test_freeze_bridges_one_gap(self, streak_module):
        """Mon active, Tue frozen, Wed active → streak continues."""
        svc = _make_service(streak_module)
        profile = _make_profile(
            last_active_date=date(2026, 4, 1),
            current_streak=3,
            streak_frozen_on=date(2026, 4, 2),
        )
        session = AsyncMock()

        svc._get_or_create_profile = AsyncMock(return_value=profile)
        svc._was_active = AsyncMock(return_value=True)

        await svc.process_streak(
            profile.patient_id, date(2026, 4, 3), postgres_session=session
        )

        assert profile.current_streak == 4
        assert profile.streak_frozen_on is None

    @pytest.mark.asyncio
    async def test_freeze_does_not_bridge_multi_day_gap(self, streak_module):
        """Mon active, Wed frozen, Thu active → streak resets (Tue missed)."""
        svc = _make_service(streak_module)
        profile = _make_profile(
            last_active_date=date(2026, 4, 1),
            current_streak=3,
            streak_frozen_on=date(2026, 4, 3),
        )
        session = AsyncMock()

        svc._get_or_create_profile = AsyncMock(return_value=profile)
        svc._was_active = AsyncMock(return_value=True)

        await svc.process_streak(
            profile.patient_id, date(2026, 4, 4), postgres_session=session
        )

        assert profile.current_streak == 1  # reset, not 4

    @pytest.mark.asyncio
    async def test_freeze_earned_every_7_days(self, streak_module):
        svc = _make_service(streak_module)
        profile = _make_profile(
            current_streak=6,
            last_active_date=date(2026, 4, 2),
            streak_freezes=1,
        )
        session = AsyncMock()

        svc._get_or_create_profile = AsyncMock(return_value=profile)
        svc._was_active = AsyncMock(return_value=True)

        await svc.process_streak(
            profile.patient_id, date(2026, 4, 3), postgres_session=session
        )

        assert profile.current_streak == 7
        assert profile.streak_freezes == 2

    @pytest.mark.asyncio
    async def test_freeze_capped_at_3(self, streak_module):
        svc = _make_service(streak_module)
        profile = _make_profile(
            current_streak=13,
            last_active_date=date(2026, 4, 2),
            streak_freezes=3,
        )
        session = AsyncMock()

        svc._get_or_create_profile = AsyncMock(return_value=profile)
        svc._was_active = AsyncMock(return_value=True)

        await svc.process_streak(
            profile.patient_id, date(2026, 4, 3), postgres_session=session
        )

        assert profile.current_streak == 14
        assert profile.streak_freezes == 3  # still 3

    @pytest.mark.asyncio
    async def test_longest_streak_updated(self, streak_module):
        svc = _make_service(streak_module)
        profile = _make_profile(
            current_streak=9,
            longest_streak=9,
            last_active_date=date(2026, 4, 2),
        )
        session = AsyncMock()

        svc._get_or_create_profile = AsyncMock(return_value=profile)
        svc._was_active = AsyncMock(return_value=True)

        await svc.process_streak(
            profile.patient_id, date(2026, 4, 3), postgres_session=session
        )

        assert profile.longest_streak == 10
