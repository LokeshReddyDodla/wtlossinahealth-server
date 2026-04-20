"""Tests for PatientDailyOverviewService._get_workout_data aggregation.

This is the integration seam between manually-logged workouts and the
unified daily snapshot consumed by the home dashboard. We only test the
workout sub-method in isolation — other sub-methods (meals, fitness, ...)
have their own tests elsewhere.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from lib.schemas.patient_daily_overview import WorkoutMetrics
from lib.services.patient_daily_overview_service import PatientDailyOverviewService
from tests.workout_logging.conftest import FakeResult, FakeSession


def _make_service():
    return PatientDailyOverviewService(
        postgres_store=SimpleNamespace(),
        clickhouse_store=SimpleNamespace(),
        meal_report_service=SimpleNamespace(),
        cgm_report_service=SimpleNamespace(),
        fitness_report_service=SimpleNamespace(),
        sleep_report_service=SimpleNamespace(),
    )


def _row(*, type_, duration=None, calories=None):
    return SimpleNamespace(
        type=type_,
        duration_minutes=duration,
        calories_burned=calories,
    )


class TestGetWorkoutData:
    @pytest.mark.asyncio
    async def test_empty_day_returns_zeros(self):
        service = _make_service()
        session = FakeSession(results=[FakeResult(rows=[])])
        metrics = await service._get_workout_data(
            str(uuid4()), date(2026, 4, 20), session
        )
        assert isinstance(metrics, WorkoutMetrics)
        assert metrics.session_count == 0
        assert metrics.total_duration_minutes == 0
        assert metrics.total_calories == 0.0
        assert metrics.types == []

    @pytest.mark.asyncio
    async def test_single_session(self):
        service = _make_service()
        session = FakeSession(
            results=[FakeResult(rows=[_row(type_="strength", duration=55, calories=420.0)])]
        )
        metrics = await service._get_workout_data(
            str(uuid4()), date(2026, 4, 20), session
        )
        assert metrics.session_count == 1
        assert metrics.total_duration_minutes == 55
        assert metrics.total_calories == 420.0
        assert metrics.types == ["strength"]

    @pytest.mark.asyncio
    async def test_multiple_sessions_same_day_aggregates(self):
        service = _make_service()
        session = FakeSession(
            results=[
                FakeResult(
                    rows=[
                        _row(type_="strength", duration=55, calories=420.0),
                        _row(type_="cardio", duration=30, calories=250.0),
                        _row(type_="cardio", duration=15, calories=None),
                    ]
                )
            ]
        )
        metrics = await service._get_workout_data(
            str(uuid4()), date(2026, 4, 20), session
        )
        assert metrics.session_count == 3
        assert metrics.total_duration_minutes == 100
        assert metrics.total_calories == 670.0
        # Types are deduplicated + sorted
        assert metrics.types == ["cardio", "strength"]

    @pytest.mark.asyncio
    async def test_null_duration_and_calories_treated_as_zero(self):
        """A session with no duration/calories logged shouldn't crash or skew totals."""
        service = _make_service()
        session = FakeSession(
            results=[
                FakeResult(
                    rows=[
                        _row(type_="mobility", duration=None, calories=None),
                        _row(type_="strength", duration=45, calories=None),
                    ]
                )
            ]
        )
        metrics = await service._get_workout_data(
            str(uuid4()), date(2026, 4, 20), session
        )
        assert metrics.session_count == 2
        assert metrics.total_duration_minutes == 45
        assert metrics.total_calories == 0.0
