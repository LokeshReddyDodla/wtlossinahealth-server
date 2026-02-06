"""Test endpoints for meal statistics processor."""

from datetime import date, datetime

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.database import get_postgres_session
from lib.dependencies.report_access import (
    ReportAccessInfo,
    get_report_access_info,
)
from lib.dependencies.service_dependencies import (
    get_meal_stats_processor,
    get_patient_profile_service,
)
from lib.schemas.meal_statistics import MealStatisticsReport, MonthlySummary
from lib.schemas.patient import CorePatientProfile
from lib.services.patient_profile_service import PatientProfileService
from lib.services.reports import MealStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/statistics",
    response_model=SuccessResponse,
    summary="Get Meal Statistics Report",
    description=(
        "Get meal statistics report for a patient within a date range. "
        "This endpoint tests the meal statistics processor. "
        "If patient_id is not provided, fetches report for the authenticated user (patients only). "
        "Patients can only fetch their own reports. "
        "Care providers must provide patient_id and can only fetch their assigned patients' reports. "
        "Admins can fetch any patient's reports."
    ),
)
async def get_meal_statistics(
    start_date: date = Query(
        ..., description="Start date for the report (YYYY-MM-DD)"
    ),
    end_date: date = Query(
        ..., description="End date for the report (YYYY-MM-DD)"
    ),
    access_info: ReportAccessInfo = Depends(get_report_access_info),
    session: AsyncSession = Depends(get_postgres_session),
    meal_stats_processor: MealStatsProcessor = Depends(get_meal_stats_processor),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
) -> SuccessResponse[MealStatisticsReport]:
    """Get meal statistics report for a date range."""
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

        report = await meal_stats_processor.get_meal_statistics_in_range(
            str(access_info.target_patient_id), start_date, end_date
        )

        if not report:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="No meal data found for the given date range",
            )

        return SuccessResponse(
            message="Meal statistics report retrieved successfully",
            data={
                "patient_info": CorePatientProfile.from_orm(patient_profile),
                "report": report,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to retrieve meal statistics report",
            detail=str(e),
        )


@router.get(
    "/monthly-summary",
    response_model=SuccessResponse,
    summary="Get Meal Monthly Summary",
    description=(
        "Get monthly meal summary for a patient within a date range. "
        "This endpoint tests the meal monthly summary processor. "
        "If patient_id is not provided, fetches report for the authenticated user (patients only). "
        "Patients can only fetch their own reports. "
        "Care providers must provide patient_id and can only fetch their assigned patients' reports. "
        "Admins can fetch any patient's reports."
    ),
)
async def get_meal_monthly_summary(
    start_date: datetime = Query(
        ..., description="Start date and time for the report (YYYY-MM-DDTHH:MM:SS)"
    ),
    end_date: datetime = Query(
        ..., description="End date and time for the report (YYYY-MM-DDTHH:MM:SS)"
    ),
    access_info: ReportAccessInfo = Depends(get_report_access_info),
    session: AsyncSession = Depends(get_postgres_session),
    meal_stats_processor: MealStatsProcessor = Depends(get_meal_stats_processor),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
) -> SuccessResponse[MonthlySummary]:
    """Get monthly meal summary for a date range."""
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

        summary = await meal_stats_processor.get_meal_month_summary(
            str(access_info.target_patient_id), start_date, end_date
        )

        if not summary:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="No meal data found for the given date range",
            )

        return SuccessResponse(
            message="Meal monthly summary retrieved successfully",
            data={
                "patient_info": CorePatientProfile.from_orm(patient_profile),
                "summary": summary,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to retrieve meal monthly summary",
            detail=str(e),
        )
