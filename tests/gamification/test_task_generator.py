from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.gamification.helpers import FakeScalarResult, FakeSession, load_module


class TestTaskGeneratorService:
    def test_habit_tasks_include_weekly_weight_on_monday(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/task_generator.py",
            "gamification_test_task_generator_habits",
        )
        service = module.TaskGeneratorService(postgres_store=None)

        # Diabetic patient gets the weight task on Mondays
        monday_tasks = service._habit_tasks(uuid4(), date(2026, 4, 6), is_diabetic=True)
        tuesday_tasks = service._habit_tasks(uuid4(), date(2026, 4, 7), is_diabetic=True)

        assert [task.task_type for task in monday_tasks] == [
            "LOG_MEAL",
            "LOG_SLEEP",
            "LOG_MOOD",
            "LOG_GLUCOSE",
            "LOG_WEIGHT",
        ]
        assert [task.task_type for task in tuesday_tasks] == [
            "LOG_MEAL",
            "LOG_SLEEP",
            "LOG_MOOD",
            "LOG_GLUCOSE",
        ]

    @pytest.mark.asyncio
    async def test_generate_weekly_quest_returns_none_when_already_exists(
        self,
        monkeypatch,
    ):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/task_generator.py",
            "gamification_test_task_generator_weekly_existing",
        )
        service = module.TaskGeneratorService(postgres_store=None)
        session = FakeSession(results=[FakeScalarResult(values=[SimpleNamespace()])])

        result = await service.generate_weekly_quest(
            patient_id=uuid4(),
            week_start=date(2026, 4, 6),
            postgres_session=session,
        )

        assert result is None
        assert session.commit_count == 0

    @pytest.mark.asyncio
    async def test_generate_weekly_quest_uses_rotation_pool(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/task_generator.py",
            "gamification_test_task_generator_weekly_new",
        )
        service = module.TaskGeneratorService(postgres_store=None)
        session = FakeSession(results=[FakeScalarResult(values=[])])
        week_start = date(2026, 4, 6)

        quest = await service.generate_weekly_quest(
            patient_id=uuid4(),
            week_start=week_start,
            postgres_session=session,
        )

        expected = module._QUEST_POOL[week_start.isocalendar()[1] % len(module._QUEST_POOL)]
        assert quest.quest_type == expected["quest_type"]
        assert quest.title == expected["title"]
        assert session.commit_count == 1
        assert session.refresh_count == 1

    @pytest.mark.asyncio
    async def test_challenge_tasks_deduplicate_patient_and_group_entries(
        self,
        monkeypatch,
    ):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/task_generator.py",
            "gamification_test_task_generator_challenges",
        )
        service = module.TaskGeneratorService(postgres_store=None)
        patient_id = uuid4()
        challenge_id = uuid4()
        group_id = uuid4()
        challenge = SimpleNamespace(
            challenge_id=challenge_id,
            title="April Steps",
            scope="group_competitive",
            target_value=100000.0,
            xp_reward=100,
        )
        patient_participant = SimpleNamespace(
            participant_type="patient",
            current_value=1200.0,
        )
        group_participant = SimpleNamespace(
            participant_type="group",
            current_value=9800.0,
        )
        session = FakeSession(
            results=[
                FakeScalarResult(
                    values=[
                        SimpleNamespace(
                            ChallengeParticipant=patient_participant,
                            Challenge=challenge,
                        )
                    ]
                ),
                FakeScalarResult(values=[group_id]),
                FakeScalarResult(
                    values=[
                        SimpleNamespace(
                            ChallengeParticipant=group_participant,
                            Challenge=challenge,
                        )
                    ]
                ),
            ]
        )

        tasks = await service._challenge_tasks(patient_id, date(2026, 4, 3), session)

        assert len(tasks) == 1
        assert tasks[0].task_type == f"CHALLENGE_TASK_{challenge_id.hex}"
        assert tasks[0].source_id == challenge_id
        assert tasks[0].description.startswith("Help you progress")

    @pytest.mark.asyncio
    async def test_fitness_plan_tasks_include_steps_and_matching_workout(
        self,
        monkeypatch,
    ):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/task_generator.py",
            "gamification_test_task_generator_fitness",
        )
        service = module.TaskGeneratorService(postgres_store=None)
        plan = SimpleNamespace(
            fitness_plan_id=uuid4(),
            steps_goal=9000,
            content={
                "weekly_sessions": [
                    {"day": "friday", "type": "strength", "duration_min": 45},
                    {"day": "friday", "type": "cardio", "duration_min": 20},
                ]
            },
        )
        session = FakeSession(results=[FakeScalarResult(values=[plan])])

        tasks = await service._fitness_plan_tasks(uuid4(), date(2026, 4, 3), session)

        assert [task.task_type for task in tasks] == [
            "HIT_STEP_GOAL",
            "COMPLETE_WORKOUT",
        ]
        assert tasks[1].title == "Strength session (45 min)"
        assert tasks[1].target_value == 45
