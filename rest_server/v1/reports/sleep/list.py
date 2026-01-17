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
from lib.dependencies.service_dependencies import get_sleep_report_service
from lib.services.sleep_report_service import SleepReportService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .api_schema import (
    ListSleepReportsResponse,
    SleepReportListResponse,
    SleepReportResponse,
)
from .router import router


@router.get(
    "",
    response_model=ListSleepReportsResponse,
    summary="List Sleep Reports",
    description=(
        "Get daily sleep reports for a patient within a date range. "
        "If patient_id is not provided, fetches reports for the authenticated user (patients only). "
        "Patients can only fetch their own reports. "
        "Care providers must provide patient_id and can only fetch their assigned patients' reports. "
        "Admins can fetch any patient's reports."
    ),
)
async def list_sleep_reports(
    start_date: date = Query(
        ..., description="Start date for report query (YYYY-MM-DD)"
    ),
    end_date: date = Query(
        ..., description="End date for report query (YYYY-MM-DD)"
    ),
    patient_id: Optional[str] = Query(
        None,
        description="Patient ID to fetch reports for (optional, defaults to authenticated user)",
    ),
    token_data: tuple = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
    sleep_report_service: SleepReportService = Depends(get_sleep_report_service),
) -> ListSleepReportsResponse:
    try:
        if end_date < start_date:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="End date must be greater than or equal to start date",
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

        # Fetch reports
        reports = await sleep_report_service.fetch_daily_reports_in_range(
            str(target_patient_id), start_date, end_date
        )

        report_responses = [
            SleepReportResponse(
                patient_id=str(target_patient_id),
                start_date=report.get("start_date"),
                end_date=report.get("end_date"),
                report_type=report.get("report_type", "daily"),
                data=report,
            )
            for report in reports
        ]

        return SuccessResponse(
            message="Sleep reports retrieved successfully",
            data=SleepReportListResponse(
                reports=report_responses,
                total=len(report_responses),
            ),
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Invalid patient ID format or date range",
            detail=str(e),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to retrieve sleep reports",
            detail=str(e),
        )
