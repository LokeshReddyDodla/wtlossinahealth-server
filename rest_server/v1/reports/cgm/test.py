"""Test endpoints for CGM statistics processor."""

from datetime import datetime
from typing import List, Optional

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.database import get_postgres_session
from lib.dependencies.report_access import (
    ReportAccessInfo,
    get_report_access_info,
)
from lib.managers.arq_task_manager import get_arq_task_manager
from lib.dependencies.service_dependencies import (
    get_cgm_stats_processor,
    get_patient_profile_service,
)
from lib.schemas.cgm_stats import CGMStats
from lib.schemas.patient import CorePatientProfile
from lib.services.patient_profile_service import PatientProfileService
from lib.services.reports import CGMStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
from lib.workers.arq.config import Queues
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/generate",
    response_model=SuccessResponse,
    summary="Generate CGM Reports",
    description=(
        "Generate CGM reports for a patient within a date range. "
        "This endpoint tests the generate_report method which creates multiple report types (custom, daily, weekly). "
        "Returns a list of reports: one custom report for the entire range, plus daily and weekly reports. "
        "If patient_id is not provided, fetches report for the authenticated user (patients only). "
        "Patients can only fetch their own reports. "
        "Care providers must provide patient_id and can only fetch their assigned patients' reports. "
        "Admins can fetch any patient's reports."
    ),
)
async def generate_cgm_reports(
    start_date: datetime = Query(
        ..., description="Start date and time for the report (YYYY-MM-DDTHH:MM:SS)"
    ),
    end_date: datetime = Query(
        ..., description="End date and time for the report (YYYY-MM-DDTHH:MM:SS)"
    ),
    access_info: ReportAccessInfo = Depends(get_report_access_info),
    session: AsyncSession = Depends(get_postgres_session),
    cgm_stats_processor: CGMStatsProcessor = Depends(get_cgm_stats_processor),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
) -> SuccessResponse[List[CGMStats]]:
    """Generate CGM reports for a date range."""
    try:
        if end_date < start_date:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="End date must be greater than or equal to start date",
            )

        patient_profile = await patient_profile_service.fetch_patient_profile(
            patient_id=str(access_info.target_patient_id),
            include_health_data=True,
        )

        reports = await cgm_stats_processor.generate_report(
            str(access_info.target_patient_id),
            start_date,
            end_date,
        )

        if not reports:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="No CGM data found for the given date range",
            )

        custom_reports = [r for r in reports if r.metadata.report_type == "custom"]
        daily_reports = [r for r in reports if r.metadata.report_type == "daily"]
        weekly_reports = [r for r in reports if r.metadata.report_type == "weekly"]

        return SuccessResponse(
            message="CGM reports generated successfully",
            data={
                "patient_info": CorePatientProfile.from_orm(patient_profile),
                "reports": reports,
                "summary": {
                    "total": len(reports),
                    "custom": len(custom_reports),
                    "daily": len(daily_reports),
                    "weekly": len(weekly_reports),
                },
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to generate CGM reports",
            detail=str(e),
        )


@router.post(
    "/vector/sync-all-daily",
    response_model=SuccessResponse,
    summary="(Test/Admin) Enqueue CGM DAILY reports → vector sync for ALL patients",
    description=(
        "Enqueues an ARQ orchestrator job which pages through ALL patients with "
        "daily CGM reports in MongoDB and enqueues per-patient vector generation "
        "jobs to the VECTORS queue. Suitable for large backfills (thousands → lacs)."
    ),
)
async def enqueue_sync_all_daily_cgm_reports_to_vector_store(
    start_date: Optional[datetime] = Query(
        None,
        description="Optional start datetime (ISO). Defaults to 1970-01-01.",
    ),
    end_date: Optional[datetime] = Query(
        None,
        description="Optional end datetime (ISO). Defaults to now+1day buffer.",
    ),
    patient_batch_size: int = Query(
        200,
        ge=1,
        le=5000,
        description="How many patients to enqueue per orchestrator page.",
    ),
    cursor_patient_id: Optional[str] = Query(
        None,
        description="Pagination cursor (patient_id). Leave empty to start from the beginning.",
    ),
    limit_patients: Optional[int] = Query(
        None,
        ge=1,
        le=100000,
        description="Optional hard cap on how many patients to enqueue (for testing).",
    ),
    _: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.ADMIN],
            check_permissions=False,
            log_activity=False,
        )
    ),
) -> SuccessResponse[dict]:
    try:
        task_manager = get_arq_task_manager()
        job_id = await task_manager.enqueue_task(
            "sync_all_daily_cgm_reports_to_vector_store",
            start_date,
            end_date,
            patient_batch_size,
            cursor_patient_id,
            limit_patients,
            task_id=(
                "api:cgm:vector:sync_all_daily:"
                f"{(start_date.date().isoformat() if start_date else 'all')}:"
                f"{(end_date.date().isoformat() if end_date else 'now')}:"
                f"{(cursor_patient_id or 'start')}"
            ),
            queue_name=Queues.DEFAULT,
        )

        return SuccessResponse(
            message="Enqueued CGM daily vector sync orchestrator job",
            data={
                "job_id": job_id,
                "queue": Queues.DEFAULT,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "patient_batch_size": patient_batch_size,
                "cursor_patient_id": cursor_patient_id,
                "limit_patients": limit_patients,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to enqueue CGM daily vector sync",
            detail=str(e),
        )
