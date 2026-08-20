"""CGM report domain (spec §5, slice 3).

The drain owns daily + weekly reports and their vectors; sensor-lifecycle
CUSTOM reports (OPEN/CLOSED periods) stay on the CSV upload task — they are
period-shaped, and only the CSV path knows the periods. Live LLU streams
reach reports purely through their dirty cells, which is what let the
30-minute reconcile cron be deleted.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from loguru import logger

from lib.derived.registry import DataDomain


def week_mondays(days: list[date]) -> list[date]:
    return sorted({d - timedelta(days=d.weekday()) for d in days})


class CGMReportDomain:
    domain = DataDomain.CGM

    async def compute_daily(self, patient_id: str, day: date) -> None:
        from lib.dependencies.service_dependencies import (
            get_cgm_report_service,
            get_cgm_stats_processor,
        )

        dt = datetime.combine(day, time.min)
        reports = await get_cgm_stats_processor().generate_report(
            patient_id, dt, dt, report_types={"daily"}
        )
        await get_cgm_report_service().save_reports_bulk(patient_id, reports)

    async def rollup(self, patient_id: str, days: list[date]) -> None:
        """Regenerate the full ISO weeks containing the dirty days — full
        weeks keep the weekly report id stable across regenerations."""
        from lib.dependencies.service_dependencies import (
            get_cgm_report_service,
            get_cgm_stats_processor,
        )

        processor = get_cgm_stats_processor()
        service = get_cgm_report_service()
        for monday in week_mondays(days):
            start = datetime.combine(monday, time.min)
            reports = await processor.generate_report(
                patient_id, start, start + timedelta(days=6), report_types={"weekly"}
            )
            await service.save_reports_bulk(patient_id, reports)

    async def vectorize(self, patient_id: str, days: list[date]) -> None:
        """Enqueue the window-based CGM vector job. The job id must be unique
        per run — arq dedups by id, and the vector task's staleness diff
        makes re-runs cheap."""
        from lib.dependencies.service_dependencies import get_patient_profile_service
        from lib.workers.arq.config import Queues
        from lib.workers.arq.redis import enqueue_job

        patient = await get_patient_profile_service().fetch_patient_profile(patient_id)
        if not patient:
            logger.warning(f"Patient profile not found for {patient_id}")
            return

        start = datetime.combine(min(days), time.min)
        end = max(datetime.combine(max(days), time.max), datetime.now())
        await enqueue_job(
            "generate_cgm_vectors",
            patient_id,
            patient.age,
            patient.gender,
            start,
            end,
            _job_id=f"cgm:vectors:{patient_id}:{datetime.now():%Y%m%d%H%M%S}",
            _queue_name=Queues.VECTORS,
        )
