"""Test endpoints for fitness statistics processor."""

from datetime import datetime

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.database import get_postgres_session
from lib.dependencies.report_access import (
    ReportAccessInfo,
    get_report_access_info,
)
from lib.dependencies.service_dependencies import (
    get_fitness_stats_processor,
    get_patient_profile_service,
)
from typing import List

from lib.schemas.fitness_stats import FitnessReport, FitnessStats
from lib.schemas.patient import CorePatientProfile
from lib.services.patient_profile_service import PatientProfileService
from lib.services.reports import FitnessStatsProcessor
from lib.services.reports.fitness.processor import FitnessReportType
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/report",
    response_model=SuccessResponse,
    summary="Get Fitness Report",
    description=(
        "Get fitness statistics report for a patient within a date range. "
        "This endpoint tests the fitness statistics processor. "
        "If patient_id is not provided, fetches report for the authenticated user (patients only). "
        "Patients can only fetch their own reports. "
        "Care providers must provide patient_id and can only fetch their assigned patients' reports. "
        "Admins can fetch any patient's reports."
    ),
)
async def get_fitness_report(
    start_date: datetime = Query(
        ..., description="Start date and time for the report (YYYY-MM-DDTHH:MM:SS)"
    ),
    end_date: datetime = Query(
        ..., description="End date and time for the report (YYYY-MM-DDTHH:MM:SS)"
    ),
    access_info: ReportAccessInfo = Depends(get_report_access_info),
    session: AsyncSession = Depends(get_postgres_session),
    fitness_stats_processor: FitnessStatsProcessor = Depends(
        get_fitness_stats_processor
    ),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
) -> SuccessResponse[FitnessReport]:
    """Get fitness report for a date range."""
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

        report = fitness_stats_processor.get_fitness_report(
            str(access_info.target_patient_id), start_date, end_date
        )

        if not report:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="No fitness data found for the given date range",
            )

        return SuccessResponse(
            message="Fitness report retrieved successfully",
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
            message="Failed to retrieve fitness report",
            detail=str(e),
        )


@router.get(
    "/generate",
    response_model=SuccessResponse,
    summary="Generate Fitness Reports",
    description=(
        "Generate fitness reports for a patient within a date range. "
        "This endpoint tests the generate_report method which can create multiple report types. "
        "Returns a list of reports (daily, weekly, monthly) based on the report_types parameter. "
        "If patient_id is not provided, fetches report for the authenticated user (patients only). "
        "Patients can only fetch their own reports. "
        "Care providers must provide patient_id and can only fetch their assigned patients' reports. "
        "Admins can fetch any patient's reports."
    ),
)
async def generate_fitness_reports(
    start_date: datetime = Query(
        ..., description="Start date and time for the report (YYYY-MM-DDTHH:MM:SS)"
    ),
    end_date: datetime = Query(
        ..., description="End date and time for the report (YYYY-MM-DDTHH:MM:SS)"
    ),
    report_types: str = Query(
        "monthly,daily,weekly",
        description="Comma-separated list of report types: 'daily', 'weekly', 'monthly'",
    ),
    access_info: ReportAccessInfo = Depends(get_report_access_info),
    session: AsyncSession = Depends(get_postgres_session),
    fitness_stats_processor: FitnessStatsProcessor = Depends(
        get_fitness_stats_processor
    ),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
) -> SuccessResponse[List[FitnessStats]]:
    """Generate fitness reports for a date range."""
    try:
        if end_date < start_date:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="End date must be greater than or equal to start date",
            )

        report_types_list = [rt.strip() for rt in report_types.split(",")]
        valid_types = [
            FitnessReportType.DAILY,
            FitnessReportType.WEEKLY,
            FitnessReportType.MONTHLY,
        ]

        for rt in report_types_list:
            if rt not in valid_types:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=f"Invalid report type: {rt}. Must be one of: {', '.join(valid_types)}",
                )

        patient_profile = await patient_profile_service.fetch_patient_profile(
            patient_id=str(access_info.target_patient_id),
            include_health_data=True,
        )

        reports = fitness_stats_processor.generate_report(
            str(access_info.target_patient_id),
            start_date,
            end_date,
            report_types=report_types_list,
        )

        if not reports:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="No fitness data found for the given date range",
            )

        return SuccessResponse(
            message="Fitness reports generated successfully",
            data={
                "patient_info": CorePatientProfile.from_orm(patient_profile),
                "reports": reports,
                "count": len(reports),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to generate fitness reports",
            detail=str(e),
        )
