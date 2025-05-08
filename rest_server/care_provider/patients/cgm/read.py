from datetime import date

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import get_cgm_report_service
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.services.cgm_report_service import CGMReportService
from lib.utils.care_provider_permissions import (CareProviderFeature,
                                                 CareProviderPermissionAction)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/report/day")
async def get_cgm_day_report(
    request: Request,
    patient_id: str = Query(...),
    date: date = Query(...),
    cgm_report_service: CGMReportService = Depends(get_cgm_report_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        day_report = await cgm_report_service.fetch_day_report(patient_id, date)

        return SuccessResponse(
            message="Day Glucose report fetched successfully",
            data=day_report,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
