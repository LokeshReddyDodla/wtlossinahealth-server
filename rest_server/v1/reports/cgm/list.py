from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.database import get_postgres_session
from lib.dependencies.report_access import (
    ReportAccessInfo,
    get_report_access_info,
)
from lib.dependencies.service_dependencies import get_cgm_report_service
from lib.services.cgm_report_service import CGMReportService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .api_schema import (
    CGMReportListResponse,
    ListCGMReportsResponse,
)
from .router import router


@router.get(
    "",
    response_model=ListCGMReportsResponse,
    summary="List CGM Reports",
    description=(
        "Get all CGM reports for a patient. "
        "If patient_id is not provided, fetches reports for the authenticated user (patients only). "
        "Patients can only fetch their own reports. "
        "Care providers must provide patient_id and can only fetch their assigned patients' reports. "
        "Admins can fetch any patient's reports."
    ),
)
async def list_cgm_reports(
    access_info: ReportAccessInfo = Depends(get_report_access_info),
    session: AsyncSession = Depends(get_postgres_session),
    cgm_report_service: CGMReportService = Depends(get_cgm_report_service),
) -> ListCGMReportsResponse:
    try:
        # Fetch all reports
        reports = await cgm_report_service.fetch_reports(str(access_info.target_patient_id))

        return SuccessResponse(
            message="CGM reports retrieved successfully",
            data=CGMReportListResponse(
                reports=reports,
                total=len(reports),
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to retrieve CGM reports",
            detail=str(e),
        )
