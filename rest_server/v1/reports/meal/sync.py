from datetime import datetime, date
from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.database import get_postgres_session
from rest_server.v1.reports.meal.api_schema import MealReportJob, SyncMealReportResponse
from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from lib.models.patient_meal import PatientMeal as PatientMealModel
from lib.models.patient import Patient as PatientModel
from lib.workers.tasks.meal.enqueue import enqueue_daily_meal_report_sync
from sqlalchemy.future import select
from loguru import logger
from .router import router


@router.post(
    "/sync",
    response_model=SyncMealReportResponse,
    summary="Sync Meal Reports",
    description=(
        "Admin-only endpoint to enqueue daily meal report generation "
        "for patients who uploaded meals on the given date."
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
    """Sync patient meals and generate daily reports."""

    stmt = (
        select(PatientMealModel.patient_id)
        .where(
            PatientMealModel.uploaded_at
            >= datetime.combine(report_date, datetime.min.time()),
            PatientMealModel.uploaded_at
            < datetime.combine(report_date, datetime.max.time()),
        )
        .distinct()
    )
    result = await session.execute(stmt)
    patient_ids = result.scalars().all()

    if not patient_ids:
        return SyncMealReportResponse(
            message=f"No meals found on {report_date}",
            report_date=report_date,
            jobs=[],
        )

    stmt = select(PatientModel).where(PatientModel.patient_id.in_(patient_ids))
    result = await session.execute(stmt)
    patients_with_meals = result.scalars().all()

    jobs = []
    for patient in patients_with_meals:
        job_id = enqueue_daily_meal_report_sync(str(patient.patient_id), report_date)
        logger.info(f"Queued report for patient {patient.patient_id}: {job_id}")
        jobs.append(
            MealReportJob(
                patient_id=str(patient.patient_id),
                job_id=job_id,
                status="queued" if job_id else "failed",
            )
        )

    return SyncMealReportResponse(
        message=f"Sync started for {len(jobs)} patients on {report_date}",
        report_date=report_date,
        jobs=jobs,
    )
