"""POST /v1/admin/ops/regenerate/{report_type} — one-tap admin report regeneration.

Enqueues report generation for a date range, for one patient or all patients.
Gap-fill semantics: the workers skip reports that already exist and are current
(CGM's filter_periods_needing_work, sleep/fitness's up-to-date checks), so this
fills missing reports rather than force-rebuilding present ones.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Awaitable, Callable, Literal, Optional

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.database import get_postgres_session
from lib.models.admin import Admin
from lib.models.patient import Patient as PatientModel
from lib.utils.http_exceptions import raise_http_exception
from lib.workers.tasks.fitness.enqueue import enqueue_process_fitness_upload_async
from lib.workers.tasks.meal.enqueue import enqueue_daily_meal_report_async
from lib.workers.tasks.sleep.enqueue import enqueue_process_sleep_upload_async
from rest_server.response_models import SuccessResponse

from .router import router

# Async enqueue helpers only: this is an async path, so the _sync variants
# (which apply nest_asyncio) are forbidden here.

ReportType = Literal["meal", "sleep", "fitness"]

# Guards a fat-fingered range × all-patients from enqueueing a runaway number of
# jobs in one request. Raise it if a real backfill needs a wider window.
MAX_RANGE_DAYS = 92


def _day_span(d: date) -> tuple[datetime, datetime]:
    """A single calendar day as a [midnight, end-of-day] datetime range."""
    return datetime.combine(d, datetime.min.time()), datetime.combine(d, datetime.max.time())


# Stable regen:* job ids dedupe repeat requests for a span while it is queued
# or running. Requires the reports worker's keep_result=0 (success AND
# failure) — a retained result key blocks re-enqueues of a stable id.


async def _regen_meal(pid: str, start: date, end: date) -> list[Optional[str]]:
    # Meal reports are per-day, so a range fans out to one job per day.
    jobs = []
    d = start
    while d <= end:
        jobs.append(
            await enqueue_daily_meal_report_async(pid, d, job_id=f"regen:meal:{pid}:{d}")
        )
        d += timedelta(days=1)
    return jobs


async def _regen_sleep(pid: str, start: date, end: date) -> list[Optional[str]]:
    lo, _ = _day_span(start)
    _, hi = _day_span(end)
    return [
        await enqueue_process_sleep_upload_async(
            pid, lo, hi, job_id=f"regen:sleep:{pid}:{start}:{end}"
        )
    ]


async def _regen_fitness(pid: str, start: date, end: date) -> list[Optional[str]]:
    lo, _ = _day_span(start)
    _, hi = _day_span(end)
    return [
        await enqueue_process_fitness_upload_async(
            pid, lo, hi, job_id=f"regen:fitness:{pid}:{start}:{end}"
        )
    ]


# Add a report type = one line here. CGM is deliberately absent: its reports are
# keyed by sensor wear periods (start/end/sensor_status), not calendar days, so a
# date range can't be turned into correct periods without reading the patient's
# real sensor sessions. Use the CGM-specific path instead of forcing it here.
# ponytail: registry of thunks, not N handlers.
REGISTRY: dict[str, Callable[[str, date, date], Awaitable[list[Optional[str]]]]] = {
    "meal": _regen_meal,
    "sleep": _regen_sleep,
    "fitness": _regen_fitness,
}


@router.post("/regenerate/{report_type}", response_model=SuccessResponse)
async def regenerate_reports(
    report_type: ReportType,
    start_date: date = Query(..., description="First day to regenerate (inclusive)."),
    end_date: date = Query(..., description="Last day to regenerate (inclusive)."),
    patient_id: Optional[str] = Query(
        None, description="Regenerate for this patient only; omit to regenerate for all patients."
    ),
    session: AsyncSession = Depends(get_postgres_session),
    current_admin: Admin = Depends(get_current_admin),
) -> SuccessResponse:
    if end_date < start_date:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="end_date must be on or after start_date",
        )

    if (end_date - start_date).days + 1 > MAX_RANGE_DAYS:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=f"Date range exceeds the {MAX_RANGE_DAYS}-day limit",
        )

    adapter = REGISTRY[report_type]

    if patient_id:
        patient_ids = [patient_id]
    else:
        result = await session.execute(select(PatientModel.patient_id))
        patient_ids = [str(pid) for pid in result.scalars().all()]

    # ponytail: enqueues one span per patient regardless of whether they have data;
    # the workers skip patients with nothing to regenerate. Fine for up to a few
    # thousand patients. Switch to the CGM sync-all-daily orchestrator pattern
    # (paged enqueue in a worker) if this ever spans lakhs.
    jobs = []
    for pid in patient_ids:
        try:
            for job_id in await adapter(pid, start_date, end_date):
                jobs.append(
                    {"patient_id": pid, "job_id": job_id, "status": "queued" if job_id else "skipped"}
                )
        except HTTPException:
            raise
        except Exception as exc:
            jobs.append({"patient_id": pid, "job_id": None, "status": "failed", "error": str(exc)})

    return SuccessResponse(
        message=(
            f"Regenerate {report_type} enqueued for {len(patient_ids)} patient(s), "
            f"{start_date} → {end_date}"
        ),
        data={
            "report_type": report_type,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "jobs": jobs,
        },
    )
