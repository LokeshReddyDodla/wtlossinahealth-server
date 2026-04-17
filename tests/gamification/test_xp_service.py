from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.gamification.helpers import FakeScalarResult, FakeSession, load_module, make_module


class TestXPService:
    @pytest.mark.asyncio
    async def test_grant_xp_applies_daily_cap_and_updates_challenge_metric(
        self,
        monkeypatch,
    ):
        challenge_calls = []

        class FakeChallengeService:
            async def update_participant_progress(self, **kwargs):
                challenge_calls.append(kwargs)

        class FakeContainer:
            def resolve(self, _cls):
                return FakeChallengeService()

        module = load_module(
            monkeypatch,
            "lib/services/gamification/xp_service.py",
            "gamification_test_xp_service",
            {
                "lib.core.container": make_module(
                    "lib.core.container",
                    container=FakeContainer(),
                ),
            },
        )
        monkeypatch.setattr(module, "level_from_xp", lambda xp: 10 if xp >= 4350 else 9)
        monkeypatch.setattr(module, "local_today", lambda _tz=None: date(2026, 4, 3))

        service = module.XPService(postgres_store=None)
        profile = SimpleNamespace(
            current_streak=14,
            total_xp=4300,
            level=9,
            title_slug=None,
        )

        async def fake_get_or_create_profile(_patient_id, _session):
            return profile

        async def fake_patient_timezone(_patient_id, _session):
            return "Asia/Kolkata"

        monkeypatch.setattr(service, "_get_or_create_profile", fake_get_or_create_profile)
        monkeypatch.setattr(service, "_patient_timezone", fake_patient_timezone)

        session = FakeSession(results=[FakeScalarResult(scalar=450)])
        amount, new_level, leveled_up = await service.grant_xp(
            patient_id=uuid4(),
            amount=100,
            source_type="task",
            source_id=None,
            description="Task reward",
            postgres_session=session,
        )

        assert amount == 50
        assert new_level == 10
        assert leveled_up is True
        assert profile.total_xp == 4350
        assert profile.level == 10
        assert len(session.added) == 1
        assert session.commit_count == 1
        assert challenge_calls == [
            {
                "patient_id": challenge_calls[0]["patient_id"],
                "metric_type": "xp_earned",
                "increment": 50.0,
            }
        ]

    @pytest.mark.asyncio
    async def test_grant_xp_respects_zero_remaining_cap(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/xp_service.py",
            "gamification_test_xp_service_zero_cap",
        )
        monkeypatch.setattr(module, "local_today", lambda _tz=None: date(2026, 4, 3))

        service = module.XPService(postgres_store=None)
        profile = SimpleNamespace(
            current_streak=0,
            total_xp=100,
            level=1,
            title_slug="newcomer",
        )

        async def fake_get_or_create_profile(_patient_id, _session):
            return profile

        async def fake_patient_timezone(_patient_id, _session):
            return "Asia/Kolkata"

        monkeypatch.setattr(service, "_get_or_create_profile", fake_get_or_create_profile)
        monkeypatch.setattr(service, "_patient_timezone", fake_patient_timezone)

        session = FakeSession(results=[FakeScalarResult(scalar=500)])
        amount, new_level, leveled_up = await service.grant_xp(
            patient_id=uuid4(),
            amount=25,
            source_type="task",
            source_id=None,
            description="No cap left",
            postgres_session=session,
        )

        assert amount == 0
        assert new_level == 1
        assert leveled_up is False
        assert profile.total_xp == 100
        assert session.added == []
        assert session.commit_count == 0

    @pytest.mark.asyncio
    async def test_get_xp_earned_today_uses_patient_local_date(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/xp_service.py",
            "gamification_test_xp_service_local_today",
        )
        service = module.XPService(postgres_store=None)

        async def fake_patient_timezone(_patient_id, _session):
            return "America/New_York"

        observed = {}

        async def fake_get_xp_earned_for_date(patient_id, target_date, **kwargs):
            observed["patient_id"] = patient_id
            observed["target_date"] = target_date
            observed["tz_name"] = kwargs.get("tz_name")
            return 77

        monkeypatch.setattr(service, "_patient_timezone", fake_patient_timezone)
        monkeypatch.setattr(service, "get_xp_earned_for_date", fake_get_xp_earned_for_date)
        monkeypatch.setattr(module, "local_today", lambda _tz=None: date(2026, 4, 2))

        result = await service.get_xp_earned_today(uuid4(), postgres_session=FakeSession())

        assert result == 77
        assert observed["target_date"] == date(2026, 4, 2)
