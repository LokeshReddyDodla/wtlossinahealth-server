"""Fitness report service — single source of truth merging all fitness data.

Combines ClickHouse synced metrics (Apple Health / Health Connect),
PostgreSQL manual workout logs, and the active fitness plan into one
per-day report with a range summary.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.clickhouse_store import ClickHouseStore
from lib.core.postgres_store import PostgresStore
from lib.models.patient_workout import PatientWorkout
from lib.schemas.fitness_report import (
    DailyActivity,
    DayPlan,
    FitnessDay,
    FitnessReportResponse,
    FitnessReportSummary,
    PlannedSession,
    WorkoutItem,
)
from lib.services.patient_fitness_plan_service import PatientFitnessPlanService
from lib.services.reports.fitness.queries import (
    generate_daily_activity_metrics_query,
    generate_daily_detected_workouts_query,
)
from lib.utils.postgres_session_decorator import with_postgres_session

logger = logging.getLogger(__name__)


class PatientFitnessReportService:
    def __init__(
        self,
        clickhouse_store: ClickHouseStore,
        postgres_store: PostgresStore,
        fitness_plan_service: PatientFitnessPlanService,
    ) -> None:
        self.clickhouse_store = clickhouse_store
        self.postgres_store = postgres_store
        self.fitness_plan_service = fitness_plan_service

    @with_postgres_session
    async def get_report(
        self,
        patient_id: str,
        start_date: date,
        end_date: date,
        *,
        postgres_session: AsyncSession,
    ) -> FitnessReportResponse:
        # ClickHouse queries run in threads (sync driver), Postgres runs sequentially
        # (async session is not safe for concurrent coroutines on the same session)
        ch_metrics_task = asyncio.to_thread(
            self._fetch_clickhouse_metrics, patient_id, start_date, end_date
        )
        ch_workouts_task = asyncio.to_thread(
            self._fetch_clickhouse_workouts, patient_id, start_date, end_date
        )

        # Postgres queries share the session — run sequentially
        pg_workouts = await self._fetch_manual_workouts(
            patient_id, start_date, end_date, postgres_session
        )
        active_plan = await self.fitness_plan_service.get_active_fitness_plan(
            patient_id, start_date, postgres_session=postgres_session
        )

        # Await ClickHouse results
        ch_metrics, ch_workouts = await asyncio.gather(
            ch_metrics_task, ch_workouts_task,
        )

        # Parse plan content
        steps_goal: Optional[float] = None
        sessions_by_day: dict[str, dict] = {}
        if active_plan and active_plan.content:
            content = active_plan.content
            if isinstance(content, dict):
                steps_goal = active_plan.steps_goal
                for session in content.get("weekly_sessions", []):
                    day_name = session.get("day", "").lower()
                    if day_name:
                        sessions_by_day[day_name] = session

        # Index ClickHouse data by date
        metrics_by_date: dict[date, DailyActivity] = {}
        for row in ch_metrics:
            day = row[0] if isinstance(row[0], date) else date.fromisoformat(str(row[0]))
            metrics_by_date[day] = DailyActivity(
                steps=int(row[1] or 0),
                active_energy=float(row[2] or 0),
                distance=float(row[3] or 0),
                flights_climbed=int(row[4] or 0),
                exercise_time=float(row[5] or 0),
            )

        # Index detected workouts by date
        detected_by_date: dict[date, list[WorkoutItem]] = {}
        for row in ch_workouts:
            day = row[0] if isinstance(row[0], date) else date.fromisoformat(str(row[0]))
            item = WorkoutItem(
                type=str(row[1]),
                duration_minutes=float(row[2] or 0),
                calories=float(row[3] or 0),
                intensity=None,
                source="apple_health",
                workout_id=None,
            )
            detected_by_date.setdefault(day, []).append(item)

        # Index manual workouts by date
        manual_by_date: dict[date, list[WorkoutItem]] = {}
        for w in pg_workouts:
            item = WorkoutItem(
                type=w.type or "other",
                duration_minutes=float(w.duration_minutes) if w.duration_minutes else None,
                calories=float(w.calories_burned) if w.calories_burned else None,
                intensity=w.intensity,
                source="app",
                workout_id=str(w.id),
            )
            manual_by_date.setdefault(w.date, []).append(item)

        # Build per-day items
        days: list[FitnessDay] = []
        current = start_date
        while current <= end_date:
            activity = metrics_by_date.get(current, DailyActivity())

            # Steps goal percentage
            if steps_goal and steps_goal > 0:
                activity.steps_goal_pct = round(activity.steps / steps_goal * 100, 1)

            # Merge workouts from both sources
            workouts = detected_by_date.get(current, []) + manual_by_date.get(current, [])

            # Plan context
            plan: Optional[DayPlan] = None
            if active_plan:
                weekday = current.strftime("%A").lower()
                session = sessions_by_day.get(weekday)
                planned = None
                if session:
                    planned = PlannedSession(
                        type=session.get("type", ""),
                        duration_min=session.get("duration_min"),
                    )
                plan = DayPlan(steps_goal=steps_goal, planned_session=planned)

            days.append(FitnessDay(
                date=current,
                activity=activity,
                workouts=workouts,
                plan=plan,
            ))
            current += timedelta(days=1)

        # Compute summary
        total_steps = sum(d.activity.steps for d in days)
        num_days = len(days) or 1
        all_workouts = [w for d in days for w in d.workouts]
        steps_goal_hit_days = None
        if steps_goal and steps_goal > 0:
            steps_goal_hit_days = sum(1 for d in days if d.activity.steps >= steps_goal)

        summary = FitnessReportSummary(
            total_steps=total_steps,
            avg_steps_per_day=round(total_steps / num_days),
            total_active_energy=round(sum(d.activity.active_energy for d in days), 1),
            total_distance=round(sum(d.activity.distance for d in days), 1),
            total_workouts=len(all_workouts),
            total_workout_minutes=round(sum(w.duration_minutes or 0 for w in all_workouts)),
            total_workout_calories=round(sum(w.calories or 0 for w in all_workouts), 1),
            steps_goal=steps_goal,
            steps_goal_hit_days=steps_goal_hit_days,
        )

        return FitnessReportResponse(
            patient_id=patient_id,
            start_date=start_date,
            end_date=end_date,
            summary=summary,
            days=days,
        )

    # -- Data fetchers --------------------------------------------------------

    def _fetch_clickhouse_metrics(
        self, patient_id: str, start_date: date, end_date: date
    ) -> list:
        query = generate_daily_activity_metrics_query(
            patient_id, str(start_date), str(end_date)
        )
        return self.clickhouse_store.client.execute(query)

    def _fetch_clickhouse_workouts(
        self, patient_id: str, start_date: date, end_date: date
    ) -> list:
        query = generate_daily_detected_workouts_query(
            patient_id, str(start_date), str(end_date)
        )
        return self.clickhouse_store.client.execute(query)

    @staticmethod
    async def _fetch_manual_workouts(
        patient_id: str,
        start_date: date,
        end_date: date,
        session: AsyncSession,
    ) -> list:
        result = await session.execute(
            select(PatientWorkout).where(
                PatientWorkout.patient_id == UUID(patient_id),
                PatientWorkout.date >= start_date,
                PatientWorkout.date <= end_date,
            )
        )
        return list(result.scalars().all())
