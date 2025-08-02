from datetime import date, datetime, time

from fastapi import Depends, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_cgm_report_service,
)
from lib.models.patient import Patient
from lib.services.cgm_report_service import CGMReportService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/report/day", response_model=SuccessResponse)
async def get_cgm_day_report(
    request: Request,
    date: date = Query(...),
    cgm_report_service: CGMReportService = Depends(get_cgm_report_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        day_report = await cgm_report_service.fetch_day_report(
            str(current_patient.patient_id), date
        )

        return SuccessResponse(
            message="Day Glucose report fetched successfully",
            data=day_report,
        )

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
