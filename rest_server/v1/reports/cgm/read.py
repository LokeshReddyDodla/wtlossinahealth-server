from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.database import get_postgres_session
from lib.dependencies.report_access import (
    ReportAccessInfo,
    get_report_access_info,
)
from lib.dependencies.service_dependencies import (
    get_cgm_report_service,
    get_patient_profile_service,
)
from lib.schemas.patient import CorePatientProfile
from lib.services.reports import CGMReportService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .api_schema import GetCGMReportResponse
from .router import router


@router.get(
    "/{report_id}",
    response_model=GetCGMReportResponse,
    summary="Get CGM Report by ID",
    description=(
        "Get a specific CGM report by report ID. "
        "Patients can only fetch their own reports. "
        "Care providers must provide patient_id and can only fetch their assigned patients' reports. "
        "Admins can fetch any patient's reports."
    ),
)
async def get_cgm_report(
    report_id: str,
    access_info: ReportAccessInfo = Depends(get_report_access_info),
    session: AsyncSession = Depends(get_postgres_session),
    cgm_report_service: CGMReportService = Depends(get_cgm_report_service),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
) -> GetCGMReportResponse:
    try:
        # Fetch report
        cgm_report = await cgm_report_service.fetch_report(
            str(access_info.target_patient_id), report_id
        )

        if not cgm_report:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="CGM report not found",
            )

        # Fetch patient profile
        patient_profile = await patient_profile_service.fetch_patient_profile(
            patient_id=str(access_info.target_patient_id),
            include_health_data=True,
        )

        return SuccessResponse(
            message="CGM report retrieved successfully",
            data={
                "patient_info": CorePatientProfile.from_orm(patient_profile),
                "report": cgm_report,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to retrieve CGM report",
            detail=str(e),
        )
