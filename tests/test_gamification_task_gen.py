"""Unit tests for task_generator — habit tasks, plan derivation, quest rotation.

Tests pure methods that don't need real SQLAlchemy (habit tasks, quest pool).
Diet/fitness plan tasks require real SA queries — tested via source contracts.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from tests.test_gamification_unit_logic import _base_stubs, _load_module


MODULE_PATH = "lib/services/gamification/task_generator.py"
MODULE_NAME = "test_task_generator"


@pytest.fixture
def task_module(monkeypatch):
    from types import SimpleNamespace

    stubs = _base_stubs()
    stubs["lib.models.patient_diet_plan"] = SimpleNamespace(
        PatientDietPlan=type("PatientDietPlan", (), {})
    )
    stubs["lib.models.patient_fitness_plan"] = SimpleNamespace(
        PatientFitnessPlan=type("PatientFitnessPlan", (), {})
    )
    return _load_module(monkeypatch, MODULE_PATH, MODULE_NAME, stubs)


class TestHabitTasks:
    def test_4_habits_on_non_monday(self, task_module):
        svc = object.__new__(task_module.TaskGeneratorService)
        tasks = svc._habit_tasks(uuid4(), date(2026, 4, 3))  # Thursday

        types = {t.task_type for t in tasks}
        assert "LOG_MEAL" in types
        assert "LOG_SLEEP" in types
        assert "LOG_MOOD" in types
        assert "LOG_GLUCOSE" in types
        assert "LOG_WEIGHT" not in types
        assert len(tasks) == 4

    def test_5_habits_on_monday(self, task_module):
        svc = object.__new__(task_module.TaskGeneratorService)
        tasks = svc._habit_tasks(uuid4(), date(2026, 4, 6))  # Monday

        types = {t.task_type for t in tasks}
        assert "LOG_WEIGHT" in types
        assert len(tasks) == 5

    def test_all_tasks_have_xp_reward(self, task_module):
        svc = object.__new__(task_module.TaskGeneratorService)
        tasks = svc._habit_tasks(uuid4(), date(2026, 4, 6))

        for task in tasks:
            assert task.xp_reward > 0

    def test_all_tasks_source_type_is_habit(self, task_module):
        svc = object.__new__(task_module.TaskGeneratorService)
        tasks = svc._habit_tasks(uuid4(), date(2026, 4, 3))

        for task in tasks:
            assert task.source_type == "habit"

    def test_all_tasks_have_correct_date(self, task_module):
        svc = object.__new__(task_module.TaskGeneratorService)
        target_date = date(2026, 4, 3)
        tasks = svc._habit_tasks(uuid4(), target_date)

        for task in tasks:
            assert task.task_date == target_date

    def test_all_tasks_have_patient_id(self, task_module):
        svc = object.__new__(task_module.TaskGeneratorService)
        pid = uuid4()
        tasks = svc._habit_tasks(pid, date(2026, 4, 3))

        for task in tasks:
            assert task.patient_id == pid


class TestQuestPool:
    def test_pool_has_entries(self, task_module):
        assert len(task_module._QUEST_POOL) > 0

    def test_all_quests_have_required_fields(self, task_module):
        for quest in task_module._QUEST_POOL:
            assert "quest_type" in quest
            assert "title" in quest
            assert "target_value" in quest
            assert "xp_reward" in quest
            assert quest["xp_reward"] > 0
            assert quest["target_value"] > 0

    def test_rotation_produces_different_quests(self, task_module):
        pool = task_module._QUEST_POOL
        if len(pool) <= 1:
            pytest.skip("Pool too small for rotation test")

        week1 = date(2026, 1, 5).isocalendar()[1]
        week2 = date(2026, 1, 12).isocalendar()[1]

        idx1 = week1 % len(pool)
        idx2 = week2 % len(pool)
        assert idx1 != idx2

    def test_all_quest_types_unique(self, task_module):
        types = [q["quest_type"] for q in task_module._QUEST_POOL]
        assert len(types) == len(set(types))


class TestXPRewards:
    def test_all_task_types_have_rewards(self, task_module):
        rewards = task_module._XP_REWARDS
        expected_types = [
            "LOG_MEAL", "HIT_CALORIE_TARGET", "HIT_PROTEIN_TARGET",
            "HIT_STEP_GOAL", "COMPLETE_WORKOUT", "LOG_SLEEP",
            "LOG_MOOD", "LOG_GLUCOSE", "LOG_WEIGHT",
        ]
        for task_type_str in expected_types:
            # Find the key that has this value
            found = any(str(k) == task_type_str for k in rewards)
            assert found, f"Missing XP reward for {task_type_str}"

    def test_all_rewards_positive(self, task_module):
        for task_type, xp in task_module._XP_REWARDS.items():
            assert xp > 0, f"{task_type} has non-positive XP: {xp}"
