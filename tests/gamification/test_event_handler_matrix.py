"""Comprehensive event-handler matrix.

Extends test_event_handler.py with parametrized coverage of:

- All 5 simple log_X hooks (sleep, mood, glucose, weight, meal)
- on_fitness_synced with steps × workout_completed combinations
- on_macro_data_available with calorie + protein toggles (4 permutations)
- _evaluate_step_goal at 80% boundary (exact, just below, just above)
- _evaluate_range_target lower-bound semantics (calorie, protein)
- Exception isolation in every hook (fire-and-forget)
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


def _load(monkeypatch, name="event_handler_matrix"):
    return load_module(
        monkeypatch,
        "lib/services/gamification/event_handler.py",
        name,
    )


def _make_handler(monkeypatch, name="evt_h"):
    module = _load(monkeypatch, name)
    handler = module.GamificationEventHandler(
        postgres_store=None,
        xp_service=SimpleNamespace(),
        achievement_evaluator=SimpleNamespace(),
    )
    return handler, module


# ── Simple log hooks: each calls _safe_complete with correct task type ─────


class TestSimpleLogHooks:
    @pytest.mark.parametrize(
        "hook_name,expected_task_type",
        [
            ("on_sleep_logged", "LOG_SLEEP"),
            ("on_mood_logged", "LOG_MOOD"),
            ("on_glucose_synced", "LOG_GLUCOSE"),
            ("on_weight_logged", "LOG_WEIGHT"),
        ],
    )
    @pytest.mark.asyncio
    async def test_hook_completes_correct_task(
        self, monkeypatch, hook_name, expected_task_type,
    ):
        handler, _ = _make_handler(monkeypatch, name=f"hook_{hook_name}")

        completed = []

        async def fake_complete(patient_id, task_type):
            completed.append((patient_id, task_type))

        monkeypatch.setattr(handler, "_complete_task", fake_complete)
        pid = uuid4()
        await getattr(handler, hook_name)(pid)
        assert completed == [(pid, expected_task_type)]

    @pytest.mark.asyncio
    async def test_meal_hook_increments_metric_then_completes_then_macro(
        self, monkeypatch,
    ):
        handler, _ = _make_handler(monkeypatch, name="meal_order")
        order = []

        async def fake_increment(patient_id, metric_type, increment):
            order.append(("increment", metric_type, increment))

        async def fake_complete(patient_id, task_type):
            order.append(("complete", task_type))

        async def fake_macro(patient_id):
            order.append(("macro",))

        monkeypatch.setattr(handler, "_increment_challenge_metric", fake_increment)
        monkeypatch.setattr(handler, "_complete_task", fake_complete)
        monkeypatch.setattr(handler, "_refresh_macro_progress", fake_macro)

        await handler.on_meal_logged(uuid4())
        assert order == [
            ("increment", "meals_logged", 1.0),
            ("complete", "LOG_MEAL"),
            ("macro",),
        ]


# ── Exception isolation ────────────────────────────────────────────────────


class TestExceptionIsolation:
    @pytest.mark.parametrize(
        "hook_name",
        ["on_sleep_logged", "on_mood_logged", "on_glucose_synced", "on_weight_logged"],
    )
    @pytest.mark.asyncio
    async def test_simple_hooks_swallow_exceptions(self, monkeypatch, hook_name):
        handler, _ = _make_handler(monkeypatch, name=f"isol_{hook_name}")

        async def boom(_pid, _t):
            raise RuntimeError("boom")

        monkeypatch.setattr(handler, "_complete_task", boom)
        # Should not raise
        await getattr(handler, hook_name)(uuid4())

    @pytest.mark.asyncio
    async def test_on_meal_swallows_metric_exception(self, monkeypatch):
        handler, _ = _make_handler(monkeypatch, name="meal_metric_boom")

        async def boom(*_a, **_k):
            raise RuntimeError("metric boom")

        async def safe_complete(_p, _t):
            return None

        async def safe_macro(_p):
            return None

        monkeypatch.setattr(handler, "_increment_challenge_metric", boom)
        monkeypatch.setattr(handler, "_complete_task", safe_complete)
        monkeypatch.setattr(handler, "_refresh_macro_progress", safe_macro)
        await handler.on_meal_logged(uuid4())  # should not raise

    @pytest.mark.asyncio
    async def test_on_fitness_swallows_internal_exception(self, monkeypatch):
        handler, _ = _make_handler(monkeypatch, name="fit_boom")

        async def boom(*_a, **_k):
            raise RuntimeError("fitness boom")

        monkeypatch.setattr(handler, "_evaluate_step_goal", boom)
        await handler.on_fitness_synced(uuid4(), steps=5000)  # should not raise

    @pytest.mark.asyncio
    async def test_on_macro_swallows_internal_exception(self, monkeypatch):
        handler, _ = _make_handler(monkeypatch, name="macro_boom")

        async def boom(*_a, **_k):
            raise RuntimeError("range boom")

        monkeypatch.setattr(handler, "_evaluate_range_target", boom)
        await handler.on_macro_data_available(
            uuid4(), total_calories=2000, total_protein=100,
        )  # should not raise


# ── on_fitness_synced steps × workout permutations ──────────────────────────


class TestOnFitnessSynced:
    """Permutations: steps None/value × workout_completed True/False = 4 cells."""

    @pytest.mark.asyncio
    async def test_no_steps_no_workout_does_nothing(self, monkeypatch):
        handler, _ = _make_handler(monkeypatch, name="fit_none")
        eval_calls, complete_calls, increment_calls = [], [], []

        async def eval_steps(_p, _s):
            eval_calls.append(_s)
        async def complete(_p, _t):
            complete_calls.append(_t)
        async def increment(_p, metric_type, increment):
            increment_calls.append((metric_type, increment))

        monkeypatch.setattr(handler, "_evaluate_step_goal", eval_steps)
        monkeypatch.setattr(handler, "_complete_task", complete)
        monkeypatch.setattr(handler, "_increment_challenge_metric", increment)
        await handler.on_fitness_synced(uuid4())
        assert eval_calls == []
        assert complete_calls == []
        assert increment_calls == []

    @pytest.mark.asyncio
    async def test_steps_only_evaluates_step_goal(self, monkeypatch):
        handler, _ = _make_handler(monkeypatch, name="fit_steps")
        eval_calls = []

        async def eval_steps(_p, s):
            eval_calls.append(s)
        async def complete(_p, _t):
            pass
        async def increment(_p, _m, _i):
            pass

        monkeypatch.setattr(handler, "_evaluate_step_goal", eval_steps)
        monkeypatch.setattr(handler, "_complete_task", complete)
        monkeypatch.setattr(handler, "_increment_challenge_metric", increment)

        await handler.on_fitness_synced(uuid4(), steps=8000)
        assert eval_calls == [8000]

    @pytest.mark.asyncio
    async def test_workout_only_completes_and_increments(self, monkeypatch):
        handler, _ = _make_handler(monkeypatch, name="fit_workout")
        complete_calls, increment_calls = [], []

        async def eval_steps(*_a, **_k):
            pass
        async def complete(*args, **kwargs):
            complete_calls.append(args[-1] if args else kwargs.get("task_type"))
        async def increment(*args, **kwargs):
            increment_calls.append((kwargs.get("metric_type"), kwargs.get("increment")))

        monkeypatch.setattr(handler, "_evaluate_step_goal", eval_steps)
        monkeypatch.setattr(handler, "_complete_task", complete)
        monkeypatch.setattr(handler, "_increment_challenge_metric", increment)

        await handler.on_fitness_synced(uuid4(), workout_completed=True)
        assert complete_calls == ["COMPLETE_WORKOUT"]
        assert increment_calls == [("workouts", 1.0)]

    @pytest.mark.asyncio
    async def test_steps_and_workout_both_processed(self, monkeypatch):
        handler, _ = _make_handler(monkeypatch, name="fit_both")
        eval_calls, complete_calls, increment_calls = [], [], []

        async def eval_steps(*args, **_k):
            eval_calls.append(args[-1])
        async def complete(*args, **kwargs):
            complete_calls.append(args[-1] if args else kwargs.get("task_type"))
        async def increment(*args, **kwargs):
            increment_calls.append((kwargs.get("metric_type"), kwargs.get("increment")))

        monkeypatch.setattr(handler, "_evaluate_step_goal", eval_steps)
        monkeypatch.setattr(handler, "_complete_task", complete)
        monkeypatch.setattr(handler, "_increment_challenge_metric", increment)

        await handler.on_fitness_synced(uuid4(), steps=12000, workout_completed=True)
        assert eval_calls == [12000]
        assert complete_calls == ["COMPLETE_WORKOUT"]
        assert increment_calls == [("workouts", 1.0)]


# ── on_macro_data_available calorie × protein permutations ──────────────────


class TestOnMacroDataAvailable:
    @pytest.mark.parametrize(
        "calories,protein,expected_evals",
        [
            (None, None, []),
            (2000, None, ["calories"]),
            (None, 100, ["protein"]),
            (2000, 100, ["calories", "protein"]),
        ],
    )
    @pytest.mark.asyncio
    async def test_macro_permutations(
        self, monkeypatch, calories, protein, expected_evals,
    ):
        from lib.schemas.gamification import (
            CALORIE_TOLERANCE_PCT,
            PROTEIN_TOLERANCE_PCT,
        )

        handler, module = _make_handler(monkeypatch, name=f"macro_{calories}_{protein}")
        evals = []

        # Pull TaskType enum from the loaded module to compare task types
        TaskType = module.TaskType

        async def fake_eval(pid, value, task_type, lower, upper):
            if task_type is TaskType.HIT_CALORIE_TARGET:
                evals.append("calories")
            elif task_type is TaskType.HIT_PROTEIN_TARGET:
                evals.append("protein")

        monkeypatch.setattr(handler, "_evaluate_range_target", fake_eval)
        await handler.on_macro_data_available(
            uuid4(), total_calories=calories, total_protein=protein,
        )
        assert evals == expected_evals


# ── _evaluate_step_goal 80% boundary ────────────────────────────────────────


class TestEvaluateStepGoalBoundary:
    """STEP_GOAL_THRESHOLD_PCT = 0.80 per helpers stub."""

    def _setup(self, monkeypatch, target, current, name):
        module = _load(monkeypatch, name=name)
        xp_calls = []
        achievement_calls = []

        class FakeXP:
            async def grant_xp(self, **kwargs):
                xp_calls.append(kwargs)
                return (kwargs.get("amount", 0), 1, False)

        class FakeAch:
            async def evaluate_all(self, **kwargs):
                achievement_calls.append(kwargs)
                return []

        handler = module.GamificationEventHandler(
            postgres_store=None,
            xp_service=FakeXP(),
            achievement_evaluator=FakeAch(),
        )
        task = SimpleNamespace(
            task_id=uuid4(),
            title="Walk",
            target_value=target,
            current_value=current,
            xp_reward=20,
            status="pending",
            completed_at=None,
        )
        session = FakeSession(results=[FakeScalarResult(values=[task])])

        async def fake_today(_p):
            return date(2026, 4, 15)
        async def fake_increment(*_a, **_k):
            pass
        async def fake_quest(*_a, **_k):
            pass
        async def fake_streak(_p):
            pass
        async def fake_post(*_a, **_k):
            pass

        monkeypatch.setattr(handler, "_patient_today", fake_today)
        monkeypatch.setattr(handler, "_increment_challenge_metric", fake_increment)
        monkeypatch.setattr(handler, "_update_quest_progress", fake_quest)
        monkeypatch.setattr(handler, "_try_process_streak", fake_streak)
        monkeypatch.setattr(handler, "_post_feed_event", fake_post)
        return handler, task, session

    @pytest.mark.parametrize(
        "target,steps,expected_status",
        [
            (10000, 7999, "pending"),    # below 80% → no completion
            (10000, 8000, "completed"),   # exactly at 80% → completes
            (10000, 8001, "completed"),   # above
            (10000, 10000, "completed"),
            (10000, 12000, "completed"),  # over-achievement also completes
        ],
    )
    @pytest.mark.asyncio
    async def test_80_percent_boundary(
        self, monkeypatch, target, steps, expected_status,
    ):
        handler, task, session = self._setup(
            monkeypatch, target, 0, name=f"step_b_{steps}",
        )
        await handler._evaluate_step_goal(uuid4(), steps, postgres_session=session)
        assert task.status == expected_status
        assert task.current_value == steps

    @pytest.mark.asyncio
    async def test_no_target_means_no_completion(self, monkeypatch):
        """Task without target_value (e.g., gen failure) — bail out."""
        handler, task, session = self._setup(monkeypatch, 0, 0, name="step_no_target")
        # Override target_value to falsy
        task.target_value = None
        # Reset session result with the modified task
        session = FakeSession(results=[FakeScalarResult(values=[task])])
        await handler._evaluate_step_goal(uuid4(), 12000, postgres_session=session)
        assert task.status == "pending"

    @pytest.mark.asyncio
    async def test_no_pending_task_does_nothing(self, monkeypatch):
        handler, _, _ = self._setup(monkeypatch, 10000, 0, name="step_no_task")
        session = FakeSession(results=[FakeScalarResult(values=[])])
        # Should not raise
        await handler._evaluate_step_goal(uuid4(), 5000, postgres_session=session)


# ── _evaluate_range_target lower-bound (calories) ──────────────────────────


class TestEvaluateRangeTarget:
    """CALORIE_TOLERANCE_PCT = 0.15 per helpers stub.

    Lower bound: target * (1 - 0.15) = target * 0.85.
    Hitting >= lower bound completes. No upper cap (over-eating still completes
    per source code comment).
    """

    def _setup(self, monkeypatch, target, name):
        module = _load(monkeypatch, name=name)

        class FakeXP:
            async def grant_xp(self, **kwargs):
                return (kwargs.get("amount", 0), 1, False)

        class FakeAch:
            async def evaluate_all(self, **kwargs):
                return []

        handler = module.GamificationEventHandler(
            postgres_store=None,
            xp_service=FakeXP(),
            achievement_evaluator=FakeAch(),
        )
        task = SimpleNamespace(
            task_id=uuid4(),
            title="Hit calories",
            target_value=target,
            current_value=0,
            xp_reward=20,
            status="pending",
            completed_at=None,
        )
        session = FakeSession(results=[FakeScalarResult(values=[task])])

        async def fake_today(_p):
            return date(2026, 4, 15)
        async def noop(*_a, **_k):
            pass

        monkeypatch.setattr(handler, "_patient_today", fake_today)
        monkeypatch.setattr(handler, "_update_challenge_progress", noop)
        monkeypatch.setattr(handler, "_update_quest_progress", noop)
        monkeypatch.setattr(handler, "_try_process_streak", noop)
        monkeypatch.setattr(handler, "_post_feed_event", noop)
        return handler, task, session, module

    @pytest.mark.parametrize(
        "target,actual,expected_status",
        [
            (2000, 1699, "pending"),    # below 85% (=1700)
            (2000, 1700, "completed"),   # exactly 85% → completes
            (2000, 1800, "completed"),
            (2000, 2000, "completed"),
            (2000, 2500, "completed"),   # over-eating still completes (no upper cap)
            (2000, 5000, "completed"),   # massively over → still completes
            (2000, 0, "pending"),
        ],
    )
    @pytest.mark.asyncio
    async def test_lower_bound_completion(
        self, monkeypatch, target, actual, expected_status,
    ):
        handler, task, session, module = self._setup(
            monkeypatch, target, name=f"range_{target}_{actual}",
        )
        await handler._evaluate_range_target(
            uuid4(), actual, module.TaskType.HIT_CALORIE_TARGET,
            0.85, 1.15, postgres_session=session,
        )
        assert task.status == expected_status
        assert task.current_value == actual
