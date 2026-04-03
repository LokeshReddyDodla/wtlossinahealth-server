from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.gamification.helpers import FakeScalarResult, FakeSession, load_module, make_module


class TestAchievementEvaluator:
    @pytest.mark.asyncio
    async def test_evaluate_all_grants_only_newly_met_achievements(self, monkeypatch):
        xp_calls = []

        class FakeXPService:
            async def grant_xp(self, **kwargs):
                xp_calls.append(kwargs)

        module = load_module(
            monkeypatch,
            "lib/services/gamification/achievement_evaluator.py",
            "gamification_test_achievement_evaluator",
        )
        service = module.AchievementEvaluator(
            postgres_store=None,
            xp_service=FakeXPService(),
        )
        achievement_met = SimpleNamespace(
            achievement_id=uuid4(),
            xp_reward=50,
            title="Week Warrior",
        )
        achievement_unmet = SimpleNamespace(
            achievement_id=uuid4(),
            xp_reward=100,
            title="Legend",
        )
        patient_id = uuid4()
        session = FakeSession(
            results=[
                FakeScalarResult(values=[]),
                FakeScalarResult(values=[achievement_met, achievement_unmet]),
            ]
        )

        async def fake_check(_patient_id, achievement, _session):
            return achievement is achievement_met

        monkeypatch.setattr(service, "_check_criteria", fake_check)

        newly_earned = await service.evaluate_all(
            patient_id,
            postgres_session=session,
        )

        assert newly_earned == [achievement_met]
        assert len(session.added) == 1
        assert session.added[0].patient_id == patient_id
        assert session.added[0].achievement_id == achievement_met.achievement_id
        assert session.commit_count == 1
        assert xp_calls == [
            {
                "patient_id": patient_id,
                "amount": 50,
                "source_type": "achievement",
                "source_id": achievement_met.achievement_id,
                "description": "Achievement: Week Warrior",
                "respect_cap": False,
            }
        ]

    @pytest.mark.asyncio
    async def test_check_group_challenges_counts_patient_and_group_participation(
        self,
        monkeypatch,
    ):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/achievement_evaluator.py",
            "gamification_test_achievement_evaluator_group_challenges",
        )
        service = module.AchievementEvaluator(postgres_store=None, xp_service=SimpleNamespace())
        session = FakeSession(
            results=[
                FakeScalarResult(scalar=1),
                FakeScalarResult(values=[uuid4(), uuid4()]),
                FakeScalarResult(scalar=2),
            ]
        )

        result = await service._check_group_challenges(uuid4(), 3, session)

        assert result is True

    @pytest.mark.asyncio
    async def test_check_custom_comeback_kid_uses_streak_resets_and_current_streak(
        self,
        monkeypatch,
    ):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/achievement_evaluator.py",
            "gamification_test_achievement_evaluator_custom",
        )
        service = module.AchievementEvaluator(postgres_store=None, xp_service=SimpleNamespace())
        profile = SimpleNamespace(streak_resets=1, current_streak=4)
        session = FakeSession(results=[FakeScalarResult(values=[profile])])

        result = await service._check_custom(uuid4(), "comeback_kid", 1, session)

        assert result is True

    @pytest.mark.asyncio
    async def test_get_progress_for_total_xp_is_capped_at_one(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/achievement_evaluator.py",
            "gamification_test_achievement_evaluator_progress",
        )
        service = module.AchievementEvaluator(postgres_store=None, xp_service=SimpleNamespace())
        achievement = SimpleNamespace(criteria_type="total_xp", criteria_threshold=100)
        session = FakeSession(results=[FakeScalarResult(scalar=180)])

        progress = await service.get_progress(
            uuid4(),
            achievement,
            postgres_session=session,
        )

        assert progress == 1.0
