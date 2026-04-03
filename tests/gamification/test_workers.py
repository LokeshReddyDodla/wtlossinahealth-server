from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.gamification.helpers import FakeScalarResult, load_module, make_module, model_class


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Session:
    def __init__(self, result):
        self.result = result

    async def execute(self, _query):
        return self.result


class TestGamificationWorkers:
    @pytest.mark.asyncio
    async def test_process_streaks_for_all_filters_by_local_hour(self, monkeypatch):
        patient_one = uuid4()
        patient_two = uuid4()
        streak_calls = []
        buddy_calls = []

        class FakeStore:
            def get_session(self):
                return _SessionContext(_Session(FakeScalarResult(values=[patient_one, patient_two])))

        class FakeResolver:
            async def resolve_timezones(self, _patient_ids):
                return {
                    str(patient_one): "Asia/Kolkata",
                    str(patient_two): "America/New_York",
                }

        class FakeStreakService:
            async def process_streak(self, patient_id, target_date):
                streak_calls.append((patient_id, target_date))

            async def process_buddy_streaks(self, patient_id, target_date):
                buddy_calls.append((patient_id, target_date))

        class FakeContainer:
            def resolve(self, cls):
                mapping = {
                    "PostgresStore": FakeStore(),
                    "StreakService": FakeStreakService(),
                    "PatientNameResolver": FakeResolver(),
                }
                return mapping[cls.__name__]

        module = load_module(
            monkeypatch,
            "lib/workers/tasks/gamification/tasks.py",
            "gamification_test_workers_streaks",
            {
                "lib.workers.tasks.base": make_module(
                    "lib.workers.tasks.base",
                    task_with_logging=lambda fn: fn,
                ),
                "lib.core.container": make_module(
                    "lib.core.container",
                    container=FakeContainer(),
                ),
                "lib.core.postgres_store": make_module(
                    "lib.core.postgres_store",
                    PostgresStore=type("PostgresStore", (), {}),
                ),
                "lib.models.patient": make_module(
                    "lib.models.patient",
                    Patient=type("Patient", (), {"patient_id": object()}),
                ),
                "lib.ai_foundation.agents.core.patient_resolver": make_module(
                    "lib.ai_foundation.agents.core.patient_resolver",
                    PatientNameResolver=type("PatientNameResolver", (), {}),
                ),
                "lib.services.gamification.streak_service": make_module(
                    "lib.services.gamification.streak_service",
                    StreakService=type("StreakService", (), {}),
                ),
            },
        )
        monkeypatch.setattr(module, "matches_local_hour", lambda tz_name, hour: tz_name == "Asia/Kolkata" and hour == 2)
        monkeypatch.setattr(module, "local_today", lambda tz_name=None: date(2026, 4, 3))

        await module.process_streaks_for_all({})

        assert streak_calls == [(patient_one, date(2026, 4, 2))]
        assert buddy_calls == [(patient_one, date(2026, 4, 2))]

    @pytest.mark.asyncio
    async def test_generate_daily_tasks_for_all_runs_weekly_quest_only_on_local_monday(
        self,
        monkeypatch,
    ):
        patient_one = uuid4()
        patient_two = uuid4()
        expired = []
        generated = []
        weekly = []

        class FakeStore:
            def get_session(self):
                return _SessionContext(_Session(FakeScalarResult(values=[patient_one, patient_two])))

        class FakeResolver:
            async def resolve_timezones(self, _patient_ids):
                return {
                    str(patient_one): "Asia/Kolkata",
                    str(patient_two): "America/New_York",
                }

        class FakeTaskGenerator:
            async def expire_old_tasks(self, patient_id, before_date):
                expired.append((patient_id, before_date))

            async def generate_daily_tasks(self, patient_id, today):
                generated.append((patient_id, today))

            async def generate_weekly_quest(self, patient_id, week_start):
                weekly.append((patient_id, week_start))

        class FakeContainer:
            def resolve(self, cls):
                mapping = {
                    "PostgresStore": FakeStore(),
                    "TaskGeneratorService": FakeTaskGenerator(),
                    "PatientNameResolver": FakeResolver(),
                }
                return mapping[cls.__name__]

        module = load_module(
            monkeypatch,
            "lib/workers/tasks/gamification/tasks.py",
            "gamification_test_workers_generate",
            {
                "lib.workers.tasks.base": make_module(
                    "lib.workers.tasks.base",
                    task_with_logging=lambda fn: fn,
                ),
                "lib.core.container": make_module(
                    "lib.core.container",
                    container=FakeContainer(),
                ),
                "lib.core.postgres_store": make_module(
                    "lib.core.postgres_store",
                    PostgresStore=type("PostgresStore", (), {}),
                ),
                "lib.models.patient": make_module(
                    "lib.models.patient",
                    Patient=type("Patient", (), {"patient_id": object()}),
                ),
                "lib.ai_foundation.agents.core.patient_resolver": make_module(
                    "lib.ai_foundation.agents.core.patient_resolver",
                    PatientNameResolver=type("PatientNameResolver", (), {}),
                ),
                "lib.services.gamification.task_generator": make_module(
                    "lib.services.gamification.task_generator",
                    TaskGeneratorService=type("TaskGeneratorService", (), {}),
                ),
            },
        )
        monkeypatch.setattr(module, "matches_local_hour", lambda _tz_name, hour: hour == 5)
        monkeypatch.setattr(
            module,
            "local_today",
            lambda tz_name=None: date(2026, 4, 6) if tz_name == "Asia/Kolkata" else date(2026, 4, 7),
        )

        await module.generate_daily_tasks_for_all({})

        assert expired == [
            (patient_one, date(2026, 4, 6)),
            (patient_two, date(2026, 4, 7)),
        ]
        assert generated == [
            (patient_one, date(2026, 4, 6)),
            (patient_two, date(2026, 4, 7)),
        ]
        assert weekly == [(patient_one, date(2026, 4, 6))]

    @pytest.mark.asyncio
    async def test_evaluate_eod_macros_only_processes_matching_local_hour(self, monkeypatch):
        patient_one = uuid4()
        patient_two = uuid4()
        macro_calls = []

        class FakeStore:
            def get_session(self):
                return _SessionContext(_Session(FakeScalarResult(values=[patient_one, patient_two])))

        class FakeResolver:
            async def resolve_timezones(self, _patient_ids):
                return {
                    str(patient_one): "Asia/Kolkata",
                    str(patient_two): "America/New_York",
                }

        class FakeEventHandler:
            async def on_macro_data_available(self, patient_id, total_calories, total_protein):
                macro_calls.append((patient_id, total_calories, total_protein))

        class FakeMealProcessor:
            async def get_meal_report_by_date(self, patient_id, day):
                if patient_id == str(patient_one):
                    return SimpleNamespace(calories=1800, proteins=130)
                return None

        class FakeContainer:
            def resolve(self, cls):
                mapping = {
                    "PostgresStore": FakeStore(),
                    "GamificationEventHandler": FakeEventHandler(),
                    "MealStatsProcessor": FakeMealProcessor(),
                    "PatientNameResolver": FakeResolver(),
                }
                return mapping[cls.__name__]

        module = load_module(
            monkeypatch,
            "lib/workers/tasks/gamification/tasks.py",
            "gamification_test_workers_macros",
            {
                "lib.workers.tasks.base": make_module(
                    "lib.workers.tasks.base",
                    task_with_logging=lambda fn: fn,
                ),
                "lib.core.container": make_module(
                    "lib.core.container",
                    container=FakeContainer(),
                ),
                "lib.core.postgres_store": make_module(
                    "lib.core.postgres_store",
                    PostgresStore=type("PostgresStore", (), {}),
                ),
                "lib.ai_foundation.agents.core.patient_resolver": make_module(
                    "lib.ai_foundation.agents.core.patient_resolver",
                    PatientNameResolver=type("PatientNameResolver", (), {}),
                ),
                "lib.models.gamification": make_module(
                    "lib.models.gamification",
                    DailyTask=model_class("DailyTask", "patient_id", "task_type", "status"),
                ),
                "lib.services.gamification.event_handler": make_module(
                    "lib.services.gamification.event_handler",
                    GamificationEventHandler=type("GamificationEventHandler", (), {}),
                ),
                "lib.services.reports.meal.processor": make_module(
                    "lib.services.reports.meal.processor",
                    MealStatsProcessor=type("MealStatsProcessor", (), {}),
                ),
            },
        )
        monkeypatch.setattr(module, "matches_local_hour", lambda tz_name, hour: tz_name == "Asia/Kolkata" and hour == 23)
        monkeypatch.setattr(module, "local_today", lambda _tz_name=None: date(2026, 4, 3))

        await module.evaluate_eod_macros({})

        assert macro_calls == [(patient_one, 1800, 130)]

    @pytest.mark.asyncio
    async def test_process_challenge_lifecycle_finalizes_each_finalizable_challenge(
        self,
        monkeypatch,
    ):
        finalized = []
        challenge_ids = [uuid4(), uuid4()]

        class FakeChallengeService:
            async def get_finalizable_challenge_ids(self):
                return challenge_ids

            async def finalize_challenge(self, challenge_id):
                finalized.append(challenge_id)

        class FakeContainer:
            def resolve(self, cls):
                mapping = {
                    "ChallengeService": FakeChallengeService(),
                    "PostgresStore": object(),
                }
                return mapping[cls.__name__]

        module = load_module(
            monkeypatch,
            "lib/workers/tasks/gamification/tasks.py",
            "gamification_test_workers_challenges",
            {
                "lib.workers.tasks.base": make_module(
                    "lib.workers.tasks.base",
                    task_with_logging=lambda fn: fn,
                ),
                "lib.core.container": make_module(
                    "lib.core.container",
                    container=FakeContainer(),
                ),
                "lib.core.postgres_store": make_module(
                    "lib.core.postgres_store",
                    PostgresStore=type("PostgresStore", (), {}),
                ),
                "lib.models.gamification": make_module(
                    "lib.models.gamification",
                    Challenge=type("Challenge", (), {}),
                ),
                "lib.services.gamification.challenge_service": make_module(
                    "lib.services.gamification.challenge_service",
                    ChallengeService=type("ChallengeService", (), {}),
                ),
            },
        )

        await module.process_challenge_lifecycle({})

        assert finalized == challenge_ids
