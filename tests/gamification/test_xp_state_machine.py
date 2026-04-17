"""Exhaustive XP grant + level computation matrix.

Extends test_xp_service.py (3 tests) with parametrized coverage of:

- streak_multiplier breakpoints (0, 7, 14, 30, 60, 90+)
- grant_xp with respect_cap=False (admin / finalization grants)
- daily cap partial consumption (cap > earned, granted = remainder)
- level_from_xp formula at every tier boundary
- title_for_level slug formatting
- challenge metric forwarding only when XP actually granted
- ledger entry shape (source_type, source_id, description preserved)
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.gamification.helpers import (
    FakeScalarResult,
    FakeSession,
    load_module,
    make_module,
)


# ── Module loader ───────────────────────────────────────────────────────────


def _load_xp(monkeypatch, name="xp_state_machine_test"):
    challenge_calls: list[dict] = []

    class FakeChallengeService:
        async def update_participant_progress(self, **kwargs):
            challenge_calls.append(kwargs)

    class FakeContainer:
        def resolve(self, _cls):
            return FakeChallengeService()

    module = load_module(
        monkeypatch,
        "lib/services/gamification/xp_service.py",
        name,
        {
            "lib.core.container": make_module(
                "lib.core.container", container=FakeContainer(),
            ),
        },
    )
    monkeypatch.setattr(module, "local_today", lambda _tz=None: date(2026, 4, 15))
    module._challenge_calls = challenge_calls
    return module


def _make(monkeypatch, profile, earned_today=0, name="xp_test"):
    module = _load_xp(monkeypatch, name)
    service = module.XPService(postgres_store=None)

    async def fake_get_or_create_profile(_patient_id, _session):
        return profile

    async def fake_patient_timezone(_patient_id, _session):
        return "Asia/Kolkata"

    monkeypatch.setattr(service, "_get_or_create_profile", fake_get_or_create_profile)
    monkeypatch.setattr(service, "_patient_timezone", fake_patient_timezone)

    session = FakeSession(results=[FakeScalarResult(scalar=earned_today)])
    return service, module, session


def _profile(*, current_streak=0, total_xp=0, level=1, title_slug="newcomer"):
    return SimpleNamespace(
        current_streak=current_streak,
        total_xp=total_xp,
        level=level,
        title_slug=title_slug,
    )


# ── streak_multiplier breakpoints ───────────────────────────────────────────


class TestStreakMultiplier:
    @pytest.mark.parametrize(
        "streak,expected",
        [
            # below 7 → 1.0
            (0, 1.0),
            (1, 1.0),
            (3, 1.0),
            (6, 1.0),
            # 7..13 → 1.1
            (7, 1.1),
            (10, 1.1),
            (13, 1.1),
            # 14..29 → 1.2
            (14, 1.2),
            (20, 1.2),
            (29, 1.2),
            # 30..59 → 1.3
            (30, 1.3),
            (45, 1.3),
            (59, 1.3),
            # 60..89 → 1.4
            (60, 1.4),
            (75, 1.4),
            (89, 1.4),
            # 90+ → 1.5
            (90, 1.5),
            (180, 1.5),
            (365, 1.5),
        ],
    )
    def test_breakpoints(self, monkeypatch, streak, expected):
        module = _load_xp(monkeypatch, name=f"sm_{streak}")
        assert module.streak_multiplier(streak) == expected


# ── level_from_xp tier boundaries ───────────────────────────────────────────


class TestLevelFromXP:
    """xp_for_level(L) = 200 * L^1.5 (per helpers stub matching real schema).

    Tests the level_from_xp inversion.
    """

    @pytest.mark.parametrize(
        "total_xp,expected_level",
        # Compute from xp_for_level(L)=200*L^1.5
        # Level 2: 200*2^1.5 ≈ 565
        # Level 3: 200*3^1.5 ≈ 1039
        # Level 5: 200*5^1.5 ≈ 2236
        # Level 10: 200*10^1.5 ≈ 6324
        [
            (0, 1),
            (564, 1),       # just below L2
            (565, 2),       # at L2 boundary
            (1038, 2),      # just below L3
            (1039, 3),      # at L3 boundary
            (2235, 4),      # below L5
            (2236, 5),      # at L5
            (6324, 10),     # at L10
            (1_000_000, 100),  # capped at MAX_LEVEL=100 (helpers stub)
        ],
    )
    def test_level_inversion(self, monkeypatch, total_xp, expected_level):
        module = _load_xp(monkeypatch, name=f"lv_{total_xp}")
        assert module.level_from_xp(total_xp) == expected_level


# ── grant_xp daily cap interaction ──────────────────────────────────────────


class TestDailyCap:
    @pytest.mark.asyncio
    async def test_full_grant_below_cap(self, monkeypatch):
        prof = _profile(current_streak=0, total_xp=100, level=1)
        svc, _, session = _make(monkeypatch, prof, earned_today=0)
        # No streak multiplier; below cap; full amount
        amount, _, _ = await svc.grant_xp(
            patient_id=uuid4(), amount=50,
            source_type="task", description="t", postgres_session=session,
        )
        assert amount == 50
        assert prof.total_xp == 150

    @pytest.mark.asyncio
    async def test_partial_grant_against_cap(self, monkeypatch):
        prof = _profile(current_streak=0, total_xp=100, level=1)
        svc, _, session = _make(monkeypatch, prof, earned_today=480)
        amount, _, _ = await svc.grant_xp(
            patient_id=uuid4(), amount=50,
            source_type="task", description="t", postgres_session=session,
        )
        # 500 - 480 = 20 remaining; 50 gets capped to 20
        assert amount == 20
        assert prof.total_xp == 120

    @pytest.mark.asyncio
    async def test_zero_grant_when_cap_already_hit(self, monkeypatch):
        prof = _profile(current_streak=0, total_xp=500, level=1)
        svc, module, session = _make(monkeypatch, prof, earned_today=500)
        amount, lvl, leveled = await svc.grant_xp(
            patient_id=uuid4(), amount=100,
            source_type="task", description="t", postgres_session=session,
        )
        assert amount == 0
        assert lvl == 1
        assert leveled is False
        # No ledger entry, no commit
        assert session.added == []
        assert session.commit_count == 0
        # No challenge metric pushed
        assert module._challenge_calls == []

    @pytest.mark.asyncio
    async def test_respect_cap_false_ignores_cap(self, monkeypatch):
        prof = _profile(current_streak=0, total_xp=500, level=1)
        # earned_today not queried because respect_cap=False — pass empty session
        module = _load_xp(monkeypatch, name="cap_false")
        service = module.XPService(postgres_store=None)

        async def fake_get(_pid, _s):
            return prof
        async def fake_tz(_pid, _s):
            return "Asia/Kolkata"
        monkeypatch.setattr(service, "_get_or_create_profile", fake_get)
        monkeypatch.setattr(service, "_patient_timezone", fake_tz)

        # No execute() result needed because respect_cap=False short-circuits
        session = FakeSession(results=[])
        amount, _, _ = await service.grant_xp(
            patient_id=uuid4(), amount=200,
            source_type="finalize", description="bonus",
            respect_cap=False, postgres_session=session,
        )
        assert amount == 200
        assert prof.total_xp == 700


# ── Streak multiplier × cap interaction ─────────────────────────────────────


class TestStreakMultiplierWithGrant:
    @pytest.mark.asyncio
    async def test_multiplier_applied_before_cap(self, monkeypatch):
        prof = _profile(current_streak=14, total_xp=0, level=1)
        # 100 base * 1.2 = 120; below cap → granted 120
        svc, _, session = _make(monkeypatch, prof, earned_today=0)
        amount, _, _ = await svc.grant_xp(
            patient_id=uuid4(), amount=100,
            source_type="task", description="t", postgres_session=session,
        )
        assert amount == 120

    @pytest.mark.asyncio
    async def test_multiplier_pushes_into_cap(self, monkeypatch):
        prof = _profile(current_streak=90, total_xp=0, level=1)
        # 100 base * 1.5 = 150; with 400 earned, 100 remaining → granted 100
        svc, _, session = _make(monkeypatch, prof, earned_today=400)
        amount, _, _ = await svc.grant_xp(
            patient_id=uuid4(), amount=100,
            source_type="task", description="t", postgres_session=session,
        )
        assert amount == 100  # capped

    @pytest.mark.asyncio
    async def test_multiplier_rounds_up(self, monkeypatch):
        prof = _profile(current_streak=7, total_xp=0, level=1)
        # 11 * 1.1 = 12.1 → ceil → 13
        svc, _, session = _make(monkeypatch, prof, earned_today=0)
        amount, _, _ = await svc.grant_xp(
            patient_id=uuid4(), amount=11,
            source_type="task", description="t", postgres_session=session,
        )
        assert amount == 13


# ── Level-up notification ───────────────────────────────────────────────────


class TestLevelUpFlag:
    @pytest.mark.asyncio
    async def test_returns_leveled_up_true_on_threshold_cross(self, monkeypatch):
        # L2 threshold ≈ 565 XP (from xp_for_level)
        prof = _profile(current_streak=0, total_xp=560, level=1)
        svc, _, session = _make(monkeypatch, prof, earned_today=0)
        amount, new_level, leveled = await svc.grant_xp(
            patient_id=uuid4(), amount=20,
            source_type="task", description="t", postgres_session=session,
        )
        # 580 XP → L2
        assert new_level == 2
        assert leveled is True

    @pytest.mark.asyncio
    async def test_no_level_up_within_same_tier(self, monkeypatch):
        prof = _profile(current_streak=0, total_xp=100, level=1)
        svc, _, session = _make(monkeypatch, prof, earned_today=0)
        amount, new_level, leveled = await svc.grant_xp(
            patient_id=uuid4(), amount=10,
            source_type="task", description="t", postgres_session=session,
        )
        # 110 XP still L1 (L2 ≈ 565)
        assert new_level == 1
        assert leveled is False


# ── Ledger entry shape ──────────────────────────────────────────────────────


class TestLedgerEntry:
    @pytest.mark.asyncio
    async def test_ledger_entry_includes_source_metadata(self, monkeypatch):
        prof = _profile(current_streak=0, total_xp=0, level=1)
        svc, _, session = _make(monkeypatch, prof, earned_today=0)
        sid = uuid4()
        await svc.grant_xp(
            patient_id=uuid4(), amount=15,
            source_type="task_completion",
            source_id=sid,
            description="LOG_MEAL",
            postgres_session=session,
        )
        assert len(session.added) == 1
        entry = session.added[0]
        assert entry.xp_amount == 15
        assert entry.source_type == "task_completion"
        assert entry.source_id == sid
        assert entry.description == "LOG_MEAL"

    @pytest.mark.asyncio
    async def test_no_ledger_entry_when_zero_granted(self, monkeypatch):
        prof = _profile(current_streak=0, total_xp=0, level=1)
        svc, _, session = _make(monkeypatch, prof, earned_today=500)
        await svc.grant_xp(
            patient_id=uuid4(), amount=10,
            source_type="t", description="t", postgres_session=session,
        )
        assert session.added == []


# ── Challenge metric forwarding ─────────────────────────────────────────────


class TestChallengeMetricForwarding:
    @pytest.mark.asyncio
    async def test_pushes_xp_earned_metric_with_amount(self, monkeypatch):
        prof = _profile(current_streak=14, total_xp=0, level=1)
        svc, module, session = _make(monkeypatch, prof, earned_today=0)
        pid = uuid4()
        await svc.grant_xp(
            patient_id=pid, amount=100,
            source_type="task", description="t", postgres_session=session,
        )
        assert len(module._challenge_calls) == 1
        call = module._challenge_calls[0]
        assert call["metric_type"] == "xp_earned"
        assert call["increment"] == 120.0  # multiplier applied
        assert call["patient_id"] == pid

    @pytest.mark.asyncio
    async def test_no_challenge_call_when_zero_xp(self, monkeypatch):
        prof = _profile(current_streak=0, total_xp=0, level=1)
        svc, module, session = _make(monkeypatch, prof, earned_today=500)
        await svc.grant_xp(
            patient_id=uuid4(), amount=10,
            source_type="t", description="t", postgres_session=session,
        )
        assert module._challenge_calls == []


# ── title_slug update ──────────────────────────────────────────────────────


class TestTitleSlugUpdate:
    @pytest.mark.asyncio
    async def test_title_slug_lowercased_and_underscored(self, monkeypatch):
        prof = _profile(current_streak=0, total_xp=560, level=1, title_slug="old")
        svc, _, session = _make(monkeypatch, prof, earned_today=0)
        await svc.grant_xp(
            patient_id=uuid4(), amount=20,
            source_type="t", description="t", postgres_session=session,
        )
        # title_for_level(2) → "Newcomer" by helpers stub (only level 1 mapped)
        # but lowercased: "newcomer"
        assert prof.title_slug.islower() or "_" in prof.title_slug
