from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.gamification.helpers import FakeScalarResult, FakeSession, load_module, make_module


class TestGamificationEventHandler:
    @pytest.mark.asyncio
    async def test_on_meal_logged_updates_challenge_progress_before_task_completion(
        self,
        monkeypatch,
    ):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/event_handler.py",
            "gamification_test_event_handler_meal",
        )
        handler = module.GamificationEventHandler(
            postgres_store=None,
            xp_service=SimpleNamespace(),
            achievement_evaluator=SimpleNamespace(),
        )
        calls = []

        async def fake_increment(patient_id, metric_type, increment):
            calls.append(("increment", patient_id, metric_type, increment))

        async def fake_complete(patient_id, task_type):
            calls.append(("complete", patient_id, task_type))

        monkeypatch.setattr(handler, "_increment_challenge_metric", fake_increment)
        monkeypatch.setattr(handler, "_complete_task", fake_complete)
        patient_id = uuid4()

        await handler.on_meal_logged(patient_id)

        assert calls == [
            ("increment", patient_id, "meals_logged", 1.0),
            ("complete", patient_id, "LOG_MEAL"),
        ]

    @pytest.mark.asyncio
    async def test_evaluate_step_goal_increments_delta_and_completes_task(
        self,
        monkeypatch,
    ):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/event_handler.py",
            "gamification_test_event_handler_steps",
        )
        xp_calls = []
        quest_calls = []
        challenge_calls = []
        achievement_calls = []

        class FakeXPService:
            async def grant_xp(self, **kwargs):
                xp_calls.append(kwargs)
                # Production unpacks (xp_granted, new_level, leveled_up)
                return (kwargs.get("amount", 0), 1, False)

        class FakeAchievements:
            async def evaluate_all(self, **kwargs):
                achievement_calls.append(kwargs)
                return []  # Production iterates the result

        handler = module.GamificationEventHandler(
            postgres_store=None,
            xp_service=FakeXPService(),
            achievement_evaluator=FakeAchievements(),
        )
        task = SimpleNamespace(
            task_id=uuid4(),
            title="Walk 10000 steps",
            target_value=10000,
            current_value=3000,
            xp_reward=30,
            status="pending",
            completed_at=None,
        )
        session = FakeSession(results=[FakeScalarResult(values=[task])])

        async def fake_patient_today(_patient_id):
            return date(2026, 4, 3)

        async def fake_increment(patient_id, metric_type, increment):
            challenge_calls.append((patient_id, metric_type, increment))

        async def fake_update_quest(patient_id, task_type):
            quest_calls.append((patient_id, task_type))

        monkeypatch.setattr(handler, "_patient_today", fake_patient_today)
        monkeypatch.setattr(handler, "_increment_challenge_metric", fake_increment)
        monkeypatch.setattr(handler, "_update_quest_progress", fake_update_quest)

        patient_id = uuid4()
        await handler._evaluate_step_goal(
            patient_id=patient_id,
            steps=8000,
            postgres_session=session,
        )

        assert task.current_value == 8000
        assert task.status == "completed"
        assert task.completed_at is not None
        assert challenge_calls == [(patient_id, "steps", 5000)]
        assert xp_calls[0]["amount"] == 30
        assert quest_calls == [(patient_id, "HIT_STEP_GOAL")]
        assert achievement_calls == [{"patient_id": patient_id}]
        assert session.commit_count == 1

    @pytest.mark.asyncio
    async def test_update_challenge_progress_only_maps_calorie_target(self, monkeypatch):
        challenge_calls = []

        class FakeChallengeService:
            async def update_participant_progress(self, patient_id, metric_type, increment):
                challenge_calls.append((patient_id, metric_type, increment))

        class FakeContainer:
            def resolve(self, _cls):
                return FakeChallengeService()

        module = load_module(
            monkeypatch,
            "lib/services/gamification/event_handler.py",
            "gamification_test_event_handler_challenge_map",
            {
                "lib.core.container": make_module(
                    "lib.core.container",
                    container=FakeContainer(),
                ),
                "lib.services.gamification.challenge_service": make_module(
                    "lib.services.gamification.challenge_service",
                    ChallengeService=type("ChallengeService", (), {}),
                ),
            },
        )
        handler = module.GamificationEventHandler(
            postgres_store=None,
            xp_service=SimpleNamespace(),
            achievement_evaluator=SimpleNamespace(),
        )
        patient_id = uuid4()

        await handler._update_challenge_progress(patient_id, "HIT_CALORIE_TARGET")
        await handler._update_challenge_progress(patient_id, "LOG_SLEEP")

        assert challenge_calls == [(patient_id, "calorie_target_hits", 1.0)]

    @pytest.mark.asyncio
    async def test_update_quest_progress_completes_matching_weekly_quest(self, monkeypatch):
        xp_calls = []
        quest = SimpleNamespace(
            quest_id=uuid4(),
            quest_type="meals_5_of_7",
            title="Meal Tracker",
            current_value=4,
            target_value=5,
            xp_reward=100,
            status="active",
            completed_at=None,
        )
        incomplete_tasks = [
            SimpleNamespace(status="completed"),
            SimpleNamespace(status="pending"),
        ]
        session_one = FakeSession(results=[FakeScalarResult(values=[quest])])
        session_two = FakeSession(
            results=[
                FakeScalarResult(values=incomplete_tasks),
            ]
        )

        class SessionContext:
            def __init__(self, session):
                self.session = session

            async def __aenter__(self):
                return self.session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeStore:
            def __init__(self):
                self.sessions = [session_one, session_two]

            def get_session(self):
                return SessionContext(self.sessions.pop(0))

        class FakeXPService:
            async def grant_xp(self, **kwargs):
                xp_calls.append(kwargs)
                return (kwargs.get("amount", 0), 1, False)

        module = load_module(
            monkeypatch,
            "lib/services/gamification/event_handler.py",
            "gamification_test_event_handler_quest",
        )
        handler = module.GamificationEventHandler(
            postgres_store=FakeStore(),
            xp_service=FakeXPService(),
            achievement_evaluator=SimpleNamespace(),
        )

        async def fake_patient_today(_patient_id):
            return date(2026, 4, 3)

        monkeypatch.setattr(handler, "_patient_today", fake_patient_today)

        await handler._update_quest_progress(uuid4(), "LOG_MEAL")

        assert quest.current_value == 5
        assert quest.status == "completed"
        assert quest.completed_at is not None
        assert session_one.commit_count == 1
        assert xp_calls == [
            {
                "patient_id": xp_calls[0]["patient_id"],
                "amount": 100,
                "source_type": "quest",
                "source_id": quest.quest_id,
                "description": "Weekly quest: Meal Tracker",
                "respect_cap": False,
            }
        ]
