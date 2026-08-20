from collections import defaultdict
from datetime import date, datetime, time, timedelta

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.database import get_postgres_session
from lib.derived import DataDomain, mark_dirty
from lib.derived.dirty import _refresh_job_id
from lib.models.patient_meal import PatientMeal as PatientMealModel
from rest_server.v1.reports.meal.api_schema import MealReportJob, SyncMealReportResponse

from .router import router


@router.post(
    "/sync",
    response_model=SyncMealReportResponse,
    summary="Sync Meal Reports",
    description=(
        "Admin-only endpoint to regenerate daily meal reports for patients "
        "who uploaded meals on the given date."
    ),
)
async def sync_patient_meals_report(
    report_date: date = Query(default_factory=date.today),
    session: AsyncSession = Depends(get_postgres_session),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
            ],
        )
    ),
) -> SyncMealReportResponse:
    """Mark the affected days dirty and let the per-patient drain regenerate.

    Selects the meals *uploaded* in the window but marks each meal's own
    `date` — a meal logged today for yesterday regenerates yesterday's
    report, the day it actually belongs to.
    """
    window_start = datetime.combine(report_date, time.min)
    stmt = (
        select(PatientMealModel.patient_id, PatientMealModel.date)
        .where(
            PatientMealModel.uploaded_at >= window_start,
            PatientMealModel.uploaded_at < window_start + timedelta(days=1),
        )
        .distinct()
    )
    rows = (await session.execute(stmt)).all()

    if not rows:
        return SyncMealReportResponse(
            message=f"No meals found on {report_date}",
            report_date=report_date,
            jobs=[],
        )

    dates_by_patient: dict[str, set[date]] = defaultdict(set)
    for patient_id, meal_date in rows:
        dates_by_patient[str(patient_id)].add(meal_date)

    jobs = []
    for patient_id, meal_dates in dates_by_patient.items():
        await mark_dirty(patient_id, DataDomain.MEAL, sorted(meal_dates))
        jobs.append(
            MealReportJob(
                patient_id=patient_id,
                job_id=_refresh_job_id(patient_id),
                status="queued",
            )
        )

    return SyncMealReportResponse(
        message=f"Sync started for {len(jobs)} patients on {report_date}",
        report_date=report_date,
        jobs=jobs,
    )
