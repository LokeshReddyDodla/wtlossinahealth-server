"""Sleep report domain (spec §5, slice 4).

Batch-shaped: check-ins and the age-banded recommended minimum are fetched
per window, so contiguous dirty days compute as one run instead of per-day.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta

from loguru import logger

from lib.derived.dirty import contiguous_runs
from lib.derived.registry import DataDomain


def month_bounds(days: list[date]) -> list[tuple[datetime, datetime]]:
    """Full calendar-month windows containing the given days."""
    bounds = []
    for year, month in sorted({(d.year, d.month) for d in days}):
        start = datetime(year, month, 1)
        next_month = datetime(year + (month == 12), month % 12 + 1, 1)
        bounds.append((start, next_month - timedelta(seconds=1)))
    return bounds


def week_windows(days: list[date]) -> list[tuple[datetime, datetime]]:
    """Full ISO-week windows containing the given days — full weeks keep
    the weekly report id stable across regenerations."""
    mondays = sorted({d - timedelta(days=d.weekday()) for d in days})
    return [
        (datetime.combine(m, time.min), datetime.combine(m + timedelta(days=6), time.max))
        for m in mondays
    ]


class SleepReportDomain:
    domain = DataDomain.SLEEP

    async def _generate(self, patient_id: str, start: datetime, end: datetime, types: list[str]) -> None:
        from lib.dependencies.service_dependencies import (
            get_sleep_report_service,
            get_sleep_stats_processor,
        )

        processor = get_sleep_stats_processor()
        checkins = await processor._fetch_sleep_checkins(patient_id, start, end)
        rec_min = await processor._recommended_sleep_minimum(patient_id)
        # generate_report is sync ClickHouse work — keep it off the event loop.
        reports = await asyncio.to_thread(
            processor.generate_report,
            patient_id,
            start,
            end,
            report_types=types,
            sleep_checkins=checkins,
            recommended_min_minutes=rec_min,
        )
        if reports:
            await get_sleep_report_service().save_reports_bulk(patient_id, reports)

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
            "generate_sleep_vectors",
            patient_id,
            patient.age,
            patient.gender,
            datetime.combine(min(days), time.min),
            datetime.combine(max(days), time.max),
            _job_id=f"sleep:vectors:{patient_id}:{datetime.now():%Y%m%d%H%M%S}",
            _queue_name=Queues.VECTORS,
        )
