from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.database import get_postgres_session
from lib.dependencies.device_access import (
    authorize_device_access,
    resolve_profile_type,
)
from lib.dependencies.service_dependencies import get_fitness_report_service
from lib.services.fitness_report_service import FitnessReportService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .api_schema import FitnessReportResponse, GetFitnessReportResponse
from .router import router


@router.get(
    "/daily",
    response_model=GetFitnessReportResponse,
    summary="Get Daily Fitness Report",
    description=(
        "Get a daily fitness report for a specific date. "
        "If patient_id is not provided, fetches report for the authenticated user (patients only). "
        "Patients can only fetch their own reports. "
        "Care providers must provide patient_id and can only fetch their assigned patients' reports. "
        "Admins can fetch any patient's reports."
    ),
)
async def get_daily_fitness_report(
    report_date: date = Query(
        ..., description="Date for the daily report (YYYY-MM-DD)"
    ),
    patient_id: Optional[str] = Query(
        None,
        description="Patient ID (optional, defaults to authenticated user)",
    ),
    regenerate: bool = Query(
        False, description="Whether to regenerate the report if it doesn't exist"
    ),
    token_data: tuple = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
    fitness_report_service: FitnessReportService = Depends(get_fitness_report_service),
) -> GetFitnessReportResponse:
    try:
        current_user_id, role_value = token_data
        current_role = ProfileTypeEnum(role_value)

        # Care providers must provide patient_id (they don't have their own reports)
        if current_role == ProfileTypeEnum.CARE_PROVIDER and not patient_id:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="patient_id is required for care providers",
            )

        # Determine target patient_id (default to authenticated user if not provided)
        target_patient_id = UUID(patient_id) if patient_id else UUID(current_user_id)

        # Resolve the profile type of the target user
        target_role = await resolve_profile_type(session, target_patient_id)

        # Reports are only for patients
        if target_role != ProfileTypeEnum.PATIENT:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Reports are only available for patients",
            )

        # Authorize access based on roles
        await authorize_device_access(
            session=session,
            current_user_id=UUID(current_user_id),
            current_role=current_role,
            target_user_id=target_patient_id,
            target_role=target_role,
        )

        # Fetch report
        report = await fitness_report_service.fetch_daily_report(
            str(target_patient_id), report_date, regenerate=regenerate
        )

        if not report:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Fitness report not found. It may be generating.",
            )

        return SuccessResponse(
            message="Fitness report retrieved successfully",
            data=FitnessReportResponse(
                patient_id=str(target_patient_id),
                start_date=report.get("start_date"),
                end_date=report.get("end_date"),
                report_type="daily",
                data=report,
            ),
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Invalid patient ID format or date",
            detail=str(e),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to retrieve fitness report",
            detail=str(e),
        )


@router.get(
    "/weekly",
    response_model=GetFitnessReportResponse,
    summary="Get Weekly Fitness Report",
    description=(
        "Get a weekly fitness report for a specific year and week number. "
        "If patient_id is not provided, fetches report for the authenticated user (patients only). "
        "Patients can only fetch their own reports. "
        "Care providers must provide patient_id and can only fetch their assigned patients' reports. "
        "Admins can fetch any patient's reports."
    ),
)
async def get_weekly_fitness_report(
    year: int = Query(..., description="Year (e.g., 2024)"),
    week_no: int = Query(..., description="Week number (1-52)"),
    patient_id: Optional[str] = Query(
        None,
        description="Patient ID (optional, defaults to authenticated user)",
    ),
    token_data: tuple = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
    fitness_report_service: FitnessReportService = Depends(get_fitness_report_service),
) -> GetFitnessReportResponse:
    try:
        current_user_id, role_value = token_data
        current_role = ProfileTypeEnum(role_value)

        # Care providers must provide patient_id (they don't have their own reports)
        if current_role == ProfileTypeEnum.CARE_PROVIDER and not patient_id:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="patient_id is required for care providers",
            )

        # Determine target patient_id (default to authenticated user if not provided)
        target_patient_id = UUID(patient_id) if patient_id else UUID(current_user_id)

        # Resolve the profile type of the target user
        target_role = await resolve_profile_type(session, target_patient_id)

        # Reports are only for patients
        if target_role != ProfileTypeEnum.PATIENT:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Reports are only available for patients",
            )

        # Authorize access based on roles
        await authorize_device_access(
            session=session,
            current_user_id=UUID(current_user_id),
            current_role=current_role,
            target_user_id=target_patient_id,
            target_role=target_role,
        )

        # Fetch report
        report = await fitness_report_service.fetch_weekly_report(
            str(target_patient_id), year, week_no
        )

        if not report:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Fitness report not found. It may be generating.",
            )

        return SuccessResponse(
            message="Fitness report retrieved successfully",
            data=FitnessReportResponse(
                patient_id=str(target_patient_id),
                start_date=report.get("start_date"),
                end_date=report.get("end_date"),
                report_type="weekly",
                data=report,
            ),
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Invalid patient ID format or date",
            detail=str(e),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to retrieve fitness report",
            detail=str(e),
        )


@router.get(
    "/monthly",
    response_model=GetFitnessReportResponse,
    summary="Get Monthly Fitness Report",
    description=(
        "Get a monthly fitness report for a specific year and month. "
        "If patient_id is not provided, fetches report for the authenticated user (patients only). "
        "Patients can only fetch their own reports. "
        "Care providers must provide patient_id and can only fetch their assigned patients' reports. "
        "Admins can fetch any patient's reports."
    ),
)
async def get_monthly_fitness_report(
    year: int = Query(..., description="Year (e.g., 2024)"),
    month_no: int = Query(..., description="Month number (1-12)"),
    patient_id: Optional[str] = Query(
        None,
        description="Patient ID (optional, defaults to authenticated user)",
    ),
    token_data: tuple = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
    fitness_report_service: FitnessReportService = Depends(get_fitness_report_service),
) -> GetFitnessReportResponse:
    try:
        if month_no < 1 or month_no > 12:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Month number must be between 1 and 12",
            )

        current_user_id, role_value = token_data
        current_role = ProfileTypeEnum(role_value)

        # Care providers must provide patient_id (they don't have their own reports)
        if current_role == ProfileTypeEnum.CARE_PROVIDER and not patient_id:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="patient_id is required for care providers",
            )

        # Determine target patient_id (default to authenticated user if not provided)
        target_patient_id = UUID(patient_id) if patient_id else UUID(current_user_id)

        # Resolve the profile type of the target user
        target_role = await resolve_profile_type(session, target_patient_id)

        # Reports are only for patients
        if target_role != ProfileTypeEnum.PATIENT:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Reports are only available for patients",
            )

        # Authorize access based on roles
        await authorize_device_access(
            session=session,
            current_user_id=UUID(current_user_id),
            current_role=current_role,
            target_user_id=target_patient_id,
            target_role=target_role,
        )

        # Fetch report
        report = await fitness_report_service.fetch_monthly_report(
            str(target_patient_id), year, month_no
        )

        if not report:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Fitness report not found. It may be generating.",
            )

        return SuccessResponse(
            message="Fitness report retrieved successfully",
            data=FitnessReportResponse(
                patient_id=str(target_patient_id),
                start_date=report.get("start_date"),
                end_date=report.get("end_date"),
                report_type="monthly",
                data=report,
            ),
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Invalid patient ID format or date",
            detail=str(e),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to retrieve fitness report",
            detail=str(e),
        )
