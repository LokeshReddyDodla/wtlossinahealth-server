from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.gamification.helpers import FakeScalarResult, FakeSession, load_module


class TestLeaderboardService:
    @pytest.mark.asyncio
    async def test_get_leaderboard_masks_group_only_identity_outside_group_scope(
        self,
        monkeypatch,
    ):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/leaderboard_service.py",
            "gamification_test_leaderboard_service_get",
        )

        class FakeDate(date):
            @classmethod
            def today(cls):
                return cls(2026, 4, 3)

        monkeypatch.setattr(module, "date", FakeDate)
        service = module.LeaderboardService(postgres_store=None)
        viewer_id = uuid4()
        subject_id = uuid4()
        session = FakeSession(
            results=[
                FakeScalarResult(
                    values=[
                        SimpleNamespace(
                            patient_id=subject_id,
                            rank=1,
                            metric_value=450.0,
                        )
                    ]
                ),
                FakeScalarResult(
                    values=[
                        SimpleNamespace(
                            patient_id=subject_id,
                            leaderboard_visibility="group_only",
                        )
                    ]
                ),
                FakeScalarResult(scalar="Amina"),
                FakeScalarResult(scalar=12),
            ]
        )

        response = await service.get_leaderboard(
            board_type="weekly_xp",
            board_scope="facility",
            patient_id=viewer_id,
            postgres_session=session,
        )

        assert response.entries[0].patient_name == "Anonymous"
        assert response.entries[0].patient_id == "anonymous:1"
        assert response.entries[0].level == 12

    @pytest.mark.asyncio
    async def test_refresh_all_boards_calls_global_group_facility_and_challenge(
        self,
        monkeypatch,
    ):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/leaderboard_service.py",
            "gamification_test_leaderboard_service_refresh_all",
        )
        service = module.LeaderboardService(postgres_store=None)
        calls = []

        async def record(name, *args, **kwargs):
            calls.append((name, args, kwargs))

        monkeypatch.setattr(service, "refresh_weekly_xp_board", lambda *a, **k: record("weekly_xp", *a, **k))
        monkeypatch.setattr(service, "refresh_monthly_xp_board", lambda *a, **k: record("monthly_xp", *a, **k))
        monkeypatch.setattr(service, "refresh_weekly_steps_board", lambda *a, **k: record("weekly_steps", *a, **k))
        monkeypatch.setattr(service, "refresh_streak_board", lambda *a, **k: record("streak", *a, **k))
        monkeypatch.setattr(service, "refresh_challenge_board", lambda *a, **k: record("challenge", *a, **k))
        group_id = uuid4()
        facility_id = uuid4()
        challenge_id = uuid4()
        session = FakeSession(
            results=[
                FakeScalarResult(values=[group_id]),
                FakeScalarResult(values=[facility_id]),
                FakeScalarResult(values=[challenge_id]),
            ]
        )

        await service.refresh_all_boards(postgres_session=session)

        assert ("weekly_xp", (), {"postgres_session": session}) in calls
        assert ("monthly_xp", (), {"postgres_session": session}) in calls
        assert ("weekly_steps", (), {"postgres_session": session}) in calls
        assert ("streak", (), {"postgres_session": session}) in calls
        assert ("weekly_xp", (), {"scope": "group", "scope_id": group_id, "postgres_session": session}) in calls
        assert ("monthly_xp", (), {"scope": "facility", "scope_id": facility_id, "postgres_session": session}) in calls
        assert ("challenge", (challenge_id,), {"postgres_session": session}) in calls

    @pytest.mark.asyncio
    async def test_scope_patient_ids_returns_group_members(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/leaderboard_service.py",
            "gamification_test_leaderboard_service_scope_group",
        )
        service = module.LeaderboardService(postgres_store=None)
        patient_ids = [uuid4(), uuid4()]
        session = FakeSession(results=[FakeScalarResult(values=patient_ids)])

        result = await service._scope_patient_ids("group", uuid4(), session)

        assert result == patient_ids

    @pytest.mark.asyncio
    async def test_scope_patient_ids_returns_only_patient_participants_for_challenge(
        self,
        monkeypatch,
    ):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/leaderboard_service.py",
            "gamification_test_leaderboard_service_scope_challenge",
        )
        service = module.LeaderboardService(postgres_store=None)
        patient_ids = [uuid4()]
        session = FakeSession(results=[FakeScalarResult(values=patient_ids)])

        result = await service._scope_patient_ids("challenge", uuid4(), session)

        assert result == patient_ids
