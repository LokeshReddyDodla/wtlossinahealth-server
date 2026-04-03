from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from tests.gamification.helpers import FakeSession, load_module, make_module


class TestStreakService:
    @pytest.mark.asyncio
    async def test_use_freeze_decrements_count_and_sets_date(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/streak_service.py",
            "gamification_test_streak_service",
        )
        service = module.StreakService(postgres_store=None)
        profile = SimpleNamespace(
            streak_freezes=2,
            current_streak=11,
            streak_frozen_on=None,
        )

        async def fake_get_or_create_profile(_patient_id, _session):
            return profile

        monkeypatch.setattr(service, "_get_or_create_profile", fake_get_or_create_profile)
        session = FakeSession()

        result = await service.use_freeze(
            patient_id=None,
            freeze_date=date(2026, 4, 3),
            postgres_session=session,
        )

        assert result is profile
        assert profile.streak_freezes == 1
        assert profile.streak_frozen_on == date(2026, 4, 3)
        assert session.commit_count == 1
        assert session.refresh_count == 1

    @pytest.mark.asyncio
    async def test_use_freeze_rejects_when_no_freezes_available(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/streak_service.py",
            "gamification_test_streak_service_no_freezes",
        )
        service = module.StreakService(postgres_store=None)
        profile = SimpleNamespace(
            streak_freezes=0,
            current_streak=11,
            streak_frozen_on=None,
        )

        async def fake_get_or_create_profile(_patient_id, _session):
            return profile

        monkeypatch.setattr(service, "_get_or_create_profile", fake_get_or_create_profile)

        with pytest.raises(ValueError, match="No streak freezes available"):
            await service.use_freeze(
                patient_id=None,
                freeze_date=date(2026, 4, 3),
                postgres_session=FakeSession(),
            )

    @pytest.mark.asyncio
    async def test_use_freeze_rejects_when_no_active_streak(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/streak_service.py",
            "gamification_test_streak_service_inactive",
        )
        service = module.StreakService(postgres_store=None)
        profile = SimpleNamespace(
            streak_freezes=1,
            current_streak=0,
            streak_frozen_on=None,
        )

        async def fake_get_or_create_profile(_patient_id, _session):
            return profile

        monkeypatch.setattr(service, "_get_or_create_profile", fake_get_or_create_profile)

        with pytest.raises(ValueError, match="No active streak to protect"):
            await service.use_freeze(
                patient_id=None,
                freeze_date=date(2026, 4, 3),
                postgres_session=FakeSession(),
            )

    @pytest.mark.asyncio
    async def test_process_streak_grants_streak_day_metric(self, monkeypatch):
        challenge_calls = []

        class FakeChallengeService:
            async def update_participant_progress(self, **kwargs):
                challenge_calls.append(kwargs)

        class FakeContainer:
            def resolve(self, _cls):
                return FakeChallengeService()

        module = load_module(
            monkeypatch,
            "lib/services/gamification/streak_service.py",
            "gamification_test_streak_service_process",
            {
                "lib.core.container": make_module(
                    "lib.core.container",
                    container=FakeContainer(),
                ),
            },
        )
        service = module.StreakService(postgres_store=None)
        profile = SimpleNamespace(
            current_streak=6,
            longest_streak=6,
            last_active_date=date(2026, 4, 2),
            streak_frozen_on=None,
            streak_freezes=0,
        )

        async def fake_get_or_create_profile(_patient_id, _session):
            return profile

        async def fake_was_active(_patient_id, _for_date, _session):
            return True

        monkeypatch.setattr(service, "_get_or_create_profile", fake_get_or_create_profile)
        monkeypatch.setattr(service, "_was_active", fake_was_active)
        session = FakeSession()

        result = await service.process_streak(
            patient_id="p1",
            for_date=date(2026, 4, 3),
            postgres_session=session,
        )

        assert result == {"action": "incremented", "streak": 7}
        assert profile.current_streak == 7
        assert profile.longest_streak == 7
        assert profile.last_active_date == date(2026, 4, 3)
        assert profile.streak_freezes == 1
        assert session.commit_count == 1
        assert challenge_calls == [
            {
                "patient_id": "p1",
                "metric_type": "streak_days",
                "increment": 1.0,
            }
        ]
