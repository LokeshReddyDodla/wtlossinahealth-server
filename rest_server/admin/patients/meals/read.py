from datetime import date

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_meal_report_service
from lib.models.admin import Admin
from lib.models.patient import Patient
from lib.services.meal_report_service import MealReportService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/report/day")
async def get_day_meal_report(
    request: Request,
    patient_id: str = Query(...),
    date: date = Query(...),
    meal_report_service: MealReportService = Depends(get_meal_report_service),
    current_admin: Admin = Depends(get_current_admin),

):
    try:
        meal_report = await meal_report_service.fetch_daily_report(
            str(patient_id), date
        )

        return SuccessResponse(
            message="Day Meal report fetched successfully",
            data=meal_report,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
