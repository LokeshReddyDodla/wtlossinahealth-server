"""Patient Data Hub — the single read-only answer to "give me patient X's
data for a window" across meals, fitness, sleep, glucose, medications and
weight.

Composes the per-day snapshot layer (HolisticDataService) and adds sleep,
then reduces days to typed window aggregates. Features consume the hub
instead of querying Postgres/ClickHouse/Mongo directly, so cross-domain
consumers (InBody insights, summaries, future coaching) share one data path.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional
from uuid import UUID

from loguru import logger

from lib.core.clickhouse_store import ClickHouseStore
from lib.schemas.patient_data_hub import WindowAggregates
from lib.schemas.weightloss_agent.holistic import HolisticDailySnapshot
from lib.services.weightloss_agent.holistic_data_service import (
    HolisticDataService,
)

# Insight windows are capped so a long gap between scans doesn't turn into a
# giant prompt; the most recent stretch is the behaviourally relevant one.
MAX_WINDOW_DAYS = 90


def _avg(values: List[float]) -> Optional[float]:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


class PatientDataHubService:
    def __init__(
        self,
        holistic_data_service: HolisticDataService,
        clickhouse_store: ClickHouseStore,
    ) -> None:
        self.holistic_data_service = holistic_data_service
        self.clickhouse_store = clickhouse_store

    async def get_daily_snapshots(
        self, patient_id: UUID, start_date: date, end_date: date
    ) -> List[HolisticDailySnapshot]:
        """Per-day typed snapshots (meals/fitness/glucose/meds/habits/weight)."""
        return await self.holistic_data_service.get_snapshot_range(
            patient_id, start_date, end_date
        )

    async def get_window_aggregates(
        self, patient_id: UUID, start_date: date, end_date: date
    ) -> WindowAggregates:
        """Reduce a window to the cross-domain numbers consumers reason over."""

        if end_date < start_date:
            start_date, end_date = end_date, start_date
        if (end_date - start_date).days > MAX_WINDOW_DAYS:
            start_date = end_date - timedelta(days=MAX_WINDOW_DAYS)

        logger.info(
            "hub: aggregating window patient={} {}..{}",
            patient_id,
            start_date,
            end_date,
        )

        snapshots = await self.get_daily_snapshots(
            patient_id, start_date, end_date
        )

        calories, protein, carbs, fats, fiber = [], [], [], [], []
        steps_values: List[int] = []
        workouts_count = 0
        workout_minutes = 0
        exercises: set[str] = set()
        glucose_avgs, tir_values = [], []
        weights: List[float] = []
        active_meds: set[str] = set()
        glp1_active = False

        days_with_meals = days_with_steps = days_with_glucose = 0

        for snap in snapshots:
            if snap.meals and snap.meals.meals_count:
                days_with_meals += 1
                calories.append(snap.meals.total_calories)
                protein.append(snap.meals.total_proteins)
                carbs.append(snap.meals.total_carbohydrates)
                fats.append(snap.meals.total_fats)
                fiber.append(snap.meals.total_fiber)
            if snap.fitness:
                if snap.fitness.steps:
                    days_with_steps += 1
                    steps_values.append(snap.fitness.steps)
                for workout in snap.fitness.workouts:
                    workouts_count += 1
                    workout_minutes += workout.duration_minutes or 0
                    exercises.update(workout.exercises)
            if snap.glucose and snap.glucose.readings_count:
                days_with_glucose += 1
                glucose_avgs.append(snap.glucose.average_mgdl)
                tir_values.append(snap.glucose.time_in_range_percent)
            if snap.weight_kg is not None:
                weights.append(snap.weight_kg)
            if snap.medications:
                for med in snap.medications.active_medications:
                    active_meds.add(med.name)
                if snap.medications.glp1 and snap.medications.glp1.injection_date:
                    glp1_active = True

        sleep_days, avg_sleep = self._sleep_stats(
            patient_id, start_date, end_date
        )

        coverage = [
            name
            for name, has in (
                ("meals", days_with_meals > 0),
                ("fitness", days_with_steps > 0 or workouts_count > 0),
                ("sleep", sleep_days > 0),
                ("glucose", days_with_glucose > 0),
                ("weight", bool(weights)),
                ("medications", bool(active_meds) or glp1_active),
            )
            if has
        ]

        return WindowAggregates(
            patient_id=str(patient_id),
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            days_in_window=(end_date - start_date).days + 1,
            days_with_meals=days_with_meals,
            avg_daily_calories=_avg(calories),
            avg_daily_protein_g=_avg(protein),
            avg_daily_carbs_g=_avg(carbs),
            avg_daily_fats_g=_avg(fats),
            avg_daily_fiber_g=_avg(fiber),
            days_with_steps=days_with_steps,
            avg_daily_steps=(
                int(sum(steps_values) / len(steps_values))
                if steps_values
                else None
            ),
            workouts_count=workouts_count,
            workout_minutes_total=workout_minutes,
            workout_exercises=sorted(exercises)[:20],
            days_with_sleep=sleep_days,
            avg_sleep_hours=avg_sleep,
            days_with_glucose=days_with_glucose,
            avg_glucose_mgdl=_avg(glucose_avgs),
            avg_time_in_range_percent=_avg(tir_values),
            first_weight_kg=weights[0] if weights else None,
            last_weight_kg=weights[-1] if weights else None,
            active_medications=sorted(active_meds),
            glp1_active=glp1_active,
            data_coverage=coverage,
        )

    def _sleep_stats(
        self, patient_id: UUID, start_date: date, end_date: date
    ) -> tuple[int, Optional[float]]:
        """Nights with sleep data and average hours, from ClickHouse."""
        try:
            # sleep_in_bed only — stage rows (deep/light/rem/awake) subdivide
            # the same night and would double-count if summed together.
            rows = self.clickhouse_store.client.execute(
                """
                SELECT toDate(sleep_start_time) AS night,
                       SUM(sleep_duration) AS total_duration
                FROM aihealth.sleep_data
                WHERE patient_id = %(patient_id)s
                    AND type = 'sleep_in_bed'
                    AND toDate(sleep_start_time) >= %(start)s
                    AND toDate(sleep_start_time) <= %(end)s
                GROUP BY night
                """,
                {
                    "patient_id": str(patient_id),
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                },
            )
        except Exception as exc:
            logger.error(
                "hub: sleep query failed patient={}: {}", patient_id, exc
            )
            return 0, None
        if not rows:
            return 0, None
        # Device sync writes the raw value without a unit contract; normalize
        # per night: plausible hours pass through, minutes and seconds scale.
        durations_hours = []
        for _, duration in rows:
            if not duration:
                continue
            value = float(duration)
            if value > 1440:          # seconds
                value = value / 3600.0
            elif value > 24:          # minutes
                value = value / 60.0
            durations_hours.append(value)
        return len(rows), _avg(durations_hours)
