"""Fitness report domain (spec §5, slice 4).

Batch-shaped: manual workouts are fetched once per generate_report window,
so contiguous dirty days compute as one run instead of per-day.
"""

from __future__ import annotations

from datetime import date, datetime, time

from loguru import logger

from lib.derived.dirty import contiguous_runs
from lib.derived.domains.sleep import month_bounds, week_windows
from lib.derived.registry import DataDomain


class FitnessReportDomain:
    domain = DataDomain.FITNESS

    async def _generate(self, patient_id: str, start: datetime, end: datetime, types: list[str]) -> None:
        from lib.dependencies.service_dependencies import (
            get_fitness_report_service,
            get_fitness_stats_processor,
        )

        reports = await get_fitness_stats_processor().generate_report(
            patient_id, start, end, report_types=types
        )
        if reports:
            await get_fitness_report_service().save_reports_bulk(patient_id, reports)

    async def compute_days(self, patient_id: str, days: list[date]) -> None:
        for run_start, run_end in contiguous_runs(days):
            await self._generate(
                patient_id,
                datetime.combine(run_start, time.min),
                datetime.combine(run_end, time.max),
                ["daily"],
            )

    async def rollup(self, patient_id: str, days: list[date]) -> None:
        for start, end in week_windows(days):
            await self._generate(patient_id, start, end, ["weekly"])
        for start, end in month_bounds(days):
            await self._generate(patient_id, start, end, ["monthly"])

    async def vectorize(self, patient_id: str, days: list[date]) -> None:
        from lib.dependencies.service_dependencies import get_patient_profile_service
        from lib.workers.arq.config import Queues
        from lib.workers.arq.redis import enqueue_job

        patient = await get_patient_profile_service().fetch_patient_profile(patient_id)
        if not patient:
            logger.warning(f"Patient profile not found for {patient_id}")
            return
        await enqueue_job(
            "generate_fitness_vectors",
            patient_id,
            patient.age,
            patient.gender,
            datetime.combine(min(days), time.min),
            datetime.combine(max(days), time.max),
            _job_id=f"fitness:vectors:{patient_id}:{datetime.now():%Y%m%d%H%M%S}",
            _queue_name=Queues.VECTORS,
        )
