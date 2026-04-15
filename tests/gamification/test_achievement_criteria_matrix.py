"""Boundary matrix for AchievementEvaluator._check_criteria.

Existing test_achievement_evaluator.py covers evaluate_all idempotency
and 3 specific criteria types. This file exhaustively exercises the
threshold-check semantics for every individual criteria type, including
boundary values (threshold-1, threshold, threshold+10) and missing-data
cases (NULL profile, count=0).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.gamification.helpers import (
    FakeScalarResult,
    FakeSession,
    load_module,
    make_module,
)


def _load(monkeypatch, name="achievement_criteria_test"):
    return load_module(
        monkeypatch,
        "lib/services/gamification/achievement_evaluator.py",
        name,
    )


def _service(monkeypatch, name="achievement_criteria_svc"):
    module = _load(monkeypatch, name)
    return module.AchievementEvaluator(
        postgres_store=None, xp_service=None,
    ), module


def _achievement(criteria_type, threshold, **kwargs):
    return SimpleNamespace(
        achievement_id=uuid4(),
        slug=f"test_{criteria_type}_{threshold}",
        title="Test",
        description=None,
        icon=None,
        category="test",
        tier="bronze",
        xp_reward=10,
        criteria_type=criteria_type,
        criteria_threshold=threshold,
        is_hidden=False,
        is_progressive=False,
        progressive_group=None,
        sort_order=1,
        **kwargs,
    )


# ── _check_streak ───────────────────────────────────────────────────────────


class TestCheckStreak:
    @pytest.mark.parametrize(
        "current_streak,threshold,expected",
        [
            (0, 7, False),
            (6, 7, False),     # threshold-1
            (7, 7, True),      # at threshold
            (8, 7, True),
            (100, 7, True),
            (None, 7, False),  # missing profile
            (0, 1, False),
            (1, 1, True),
        ],
    )
    @pytest.mark.asyncio
    async def test_streak_threshold(self, monkeypatch, current_streak, threshold, expected):
        svc, _ = _service(monkeypatch, name=f"streak_{current_streak}_{threshold}")
        session = FakeSession(results=[FakeScalarResult(scalar=current_streak)])
        result = await svc._check_streak(uuid4(), threshold, session)
        assert result is expected


# ── _check_total_xp ─────────────────────────────────────────────────────────


class TestCheckTotalXP:
    @pytest.mark.parametrize(
        "total_xp,threshold,expected",
        [
            (0, 1000, False),
            (999, 1000, False),
            (1000, 1000, True),
            (1500, 1000, True),
            (None, 1000, False),
        ],
    )
    @pytest.mark.asyncio
    async def test_xp_threshold(self, monkeypatch, total_xp, threshold, expected):
        svc, _ = _service(monkeypatch, name=f"xp_{total_xp}_{threshold}")
        session = FakeSession(results=[FakeScalarResult(scalar=total_xp)])
        result = await svc._check_total_xp(uuid4(), threshold, session)
        assert result is expected


# ── _check_level ────────────────────────────────────────────────────────────


class TestCheckLevel:
    @pytest.mark.parametrize(
        "level,threshold,expected",
        [
            (1, 5, False),
            (4, 5, False),
            (5, 5, True),
            (10, 5, True),
            (None, 5, False),
        ],
    )
    @pytest.mark.asyncio
    async def test_level_threshold(self, monkeypatch, level, threshold, expected):
        svc, _ = _service(monkeypatch, name=f"lvl_{level}_{threshold}")
        session = FakeSession(results=[FakeScalarResult(scalar=level)])
        result = await svc._check_level(uuid4(), threshold, session)
        assert result is expected


# ── _check_tasks_completed ──────────────────────────────────────────────────


class TestCheckTasksCompleted:
    @pytest.mark.parametrize(
        "count,threshold,expected",
        [
            (0, 50, False),
            (49, 50, False),
            (50, 50, True),
            (100, 50, True),
            (None, 50, False),  # NULL coalesced to 0
        ],
    )
    @pytest.mark.asyncio
    async def test_tasks_count_threshold(self, monkeypatch, count, threshold, expected):
        svc, _ = _service(monkeypatch, name=f"tc_{count}_{threshold}")
        session = FakeSession(results=[FakeScalarResult(scalar=count)])
        result = await svc._check_tasks_completed(uuid4(), threshold, session)
        assert result is expected


# ── _check_task_type_count (for meals_logged, steps_hit, etc.) ──────────────


class TestCheckTaskTypeCount:
    @pytest.mark.parametrize(
        "task_type,count,threshold,expected",
        [
            ("LOG_MEAL", 99, 100, False),
            ("LOG_MEAL", 100, 100, True),
            ("HIT_STEP_GOAL", 50, 50, True),
            ("COMPLETE_WORKOUT", 0, 1, False),
            ("COMPLETE_WORKOUT", 1, 1, True),
            ("LOG_MOOD", 200, 100, True),
        ],
    )
    @pytest.mark.asyncio
    async def test_task_type_count(
        self, monkeypatch, task_type, count, threshold, expected,
    ):
        svc, _ = _service(monkeypatch, name=f"ttc_{task_type}_{count}")
        session = FakeSession(results=[FakeScalarResult(scalar=count)])
        result = await svc._check_task_type_count(
            uuid4(), task_type, threshold, session,
        )
        assert result is expected


# ── _check_buddy_count ──────────────────────────────────────────────────────


class TestCheckBuddyCount:
    @pytest.mark.parametrize(
        "active_count,threshold,expected",
        [
            (0, 1, False),
            (1, 1, True),
            (3, 1, True),
            (2, 3, False),
            (3, 3, True),
        ],
    )
    @pytest.mark.asyncio
    async def test_buddy_count_threshold(
        self, monkeypatch, active_count, threshold, expected,
    ):
        svc, _ = _service(monkeypatch, name=f"bc_{active_count}_{threshold}")
        session = FakeSession(results=[FakeScalarResult(scalar=active_count)])
        result = await svc._check_buddy_count(uuid4(), threshold, session)
        assert result is expected


# ── _check_cheers_sent ──────────────────────────────────────────────────────


class TestCheckCheersSent:
    @pytest.mark.parametrize(
        "count,threshold,expected",
        [
            (0, 1, False),
            (1, 1, True),
            (4, 5, False),
            (5, 5, True),
        ],
    )
    @pytest.mark.asyncio
    async def test_cheers_threshold(self, monkeypatch, count, threshold, expected):
        # Need to stub Cheer model — base_stubs already provides it
        svc, _ = _service(monkeypatch, name=f"cs_{count}_{threshold}")
        session = FakeSession(results=[FakeScalarResult(scalar=count)])
        result = await svc._check_cheers_sent(uuid4(), threshold, session)
        assert result is expected


# ── evaluate_all idempotency: already-earned skipped ───────────────────────


class TestEvaluateAllSkipsAlreadyEarned:
    @pytest.mark.asyncio
    async def test_no_duplicate_grant_for_already_earned(self, monkeypatch):
        from unittest.mock import AsyncMock

        svc, _ = _service(monkeypatch, name="dedup_check")

        a1 = _achievement("streak_days", 7)
        a2 = _achievement("total_xp", 1000)

        # Patient already earned a1
        earned_ids = [a1.achievement_id]
        all_achievements = [a1, a2]

        # Mock XP service grant to record calls
        grant_calls = []
        class FakeXP:
            async def grant_xp(self, **kwargs):
                grant_calls.append(kwargs)
        svc.xp_service = FakeXP()

        # Fake check: a1 still meets criteria, a2 does not
        async def fake_check(_pid, achievement, _session):
            return achievement is a1 or achievement is a2 and False
        monkeypatch.setattr(svc, "_check_criteria", fake_check)

        session = FakeSession(results=[
            FakeScalarResult(values=earned_ids),       # already-earned IDs
            FakeScalarResult(values=all_achievements),  # all achievements
        ])

        result = await svc.evaluate_all(uuid4(), postgres_session=session)
        # a1 already earned → skipped; a2 fails criteria → not granted
        assert result == []
        assert grant_calls == []
        assert session.added == []
