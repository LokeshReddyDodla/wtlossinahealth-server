from datetime import date, datetime
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
from lib.dependencies.service_dependencies import (
    get_patient_profile_service,
    get_smbg_stats_processor,
)
from lib.schemas.patient import CorePatientProfile
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.smbg.processor import SMBGStatsProcessor
from rest_server.response_models import SuccessResponse

from .api_schema import GetSMBGReportResponse
from .router import router


@router.get(
    "",
    response_model=GetSMBGReportResponse,
    summary="Get SMBG Report",
    description=(
        "Get SMBG (Self-Monitoring Blood Glucose) statistics report for a patient within a date range. "
        "If patient_id is not provided, fetches report for the authenticated user (patients only). "
        "Patients can only fetch their own reports. "
        "Care providers must provide patient_id and can only fetch their assigned patients' reports. "
        "Admins can fetch any patient's reports."
    ),
)
async def get_smbg_report(
    start_date: datetime = Query(
        ..., description="Start date and time for the report (YYYY-MM-DDTHH:MM:SS)"
    ),
    end_date: datetime = Query(
        ..., description="End date and time for the report (YYYY-MM-DDTHH:MM:SS)"
    ),
    patient_id: Optional[str] = Query(
        None,
        description="Patient ID to fetch report for (optional, defaults to authenticated user)",
    ),
    token_data: tuple = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
    smbg_stats_processor: SMBGStatsProcessor = Depends(get_smbg_stats_processor),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
) -> GetSMBGReportResponse:
    try:
        # Validate date range
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
                message="SMBG reports are only available for patients",
            )

        # Authorize access based on roles
        await authorize_device_access(
            session=session,
            current_user_id=UUID(current_user_id),
            current_role=current_role,
            target_user_id=target_patient_id,
            target_role=target_role,
        )

        # Fetch patient profile
        patient_profile = await patient_profile_service.fetch_patient_profile(
            patient_id=str(target_patient_id),
            include_health_data=True,
        )

        # Get SMBG statistics report
        smbg_report = await smbg_stats_processor.get_stats(
            str(target_patient_id), start_date, end_date, postgres_session=session
        )

        if not smbg_report:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="No SMBG data found for the given date range",
            )

        return SuccessResponse(
            message="SMBG report retrieved successfully",
            data={
                "patient_info": CorePatientProfile.from_orm(patient_profile),
                "report": smbg_report,
            },
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Invalid patient ID format",
            detail=str(e),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to retrieve SMBG report",
            detail=str(e),
        )
