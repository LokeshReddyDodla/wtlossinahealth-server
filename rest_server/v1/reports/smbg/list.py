from datetime import datetime

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.database import get_postgres_session
from lib.dependencies.report_access import (
    ReportAccessInfo,
    get_report_access_info,
)
from lib.dependencies.service_dependencies import (
    get_patient_profile_service,
    get_smbg_stats_processor,
)
from lib.schemas.patient import CorePatientProfile
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from lib.services.reports import SMBGStatsProcessor
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
    access_info: ReportAccessInfo = Depends(get_report_access_info),
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

        # Fetch patient profile
        patient_profile = await patient_profile_service.fetch_patient_profile(
            patient_id=str(access_info.target_patient_id),
            include_health_data=True,
        )

        # Get SMBG statistics report
        smbg_report = await smbg_stats_processor.get_stats(
            str(access_info.target_patient_id), start_date, end_date, postgres_session=session
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
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to retrieve SMBG report",
            detail=str(e),
        )
