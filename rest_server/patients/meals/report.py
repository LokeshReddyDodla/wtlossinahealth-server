from datetime import date

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_meal_report_service
from lib.models.patient import Patient
from lib.services.meal_report_service import MealReportService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/report")
async def get_meal_reports(
    request: Request,
    start_date: date = Query(...),
    end_date: date = Query(...),
    meal_report_service: MealReportService = Depends(get_meal_report_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        meal_reports = meal_report_service.fetch_daily_reports_in_range(
            str(current_patient.patient_id), start_date, end_date
        )

        return SuccessResponse(
            message="Meal reports fetched successfully",
            data=meal_reports,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
