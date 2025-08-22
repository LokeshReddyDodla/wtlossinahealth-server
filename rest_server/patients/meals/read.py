from datetime import date, datetime
from typing import Optional

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_meal_report_service,
    get_meal_service,
)
from lib.models.patient import Patient
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema
from lib.services.meal_report_service import MealReportService
from lib.services.meal_service import MealService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import InQueueResponse, SuccessResponse

from .router import router


@router.get(
    path="",
    response_model=SuccessResponse,
)
async def get_meals_api(
    request: Request,
    start_datetime: Optional[datetime] = Query(None),
    end_datetime: Optional[datetime] = Query(None),
    source: Optional[str] = Query(None),
    analyzed: Optional[str] = Query(None, regex="^(true|false|both)$"),
    order_by: Optional[str] = Query("time"),
    order: Optional[str] = Query("desc"),
    limit: Optional[int] = Query(None),
    meal_service: MealService = Depends(get_meal_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        meals = await meal_service.fetch_meals(
            patient_id=str(current_patient.patient_id),
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            source=source,
            analyzed=analyzed,
            order_by=order_by,
            order=order,
            limit=limit,
        )

        meals = [PatientMealSchema.from_orm(meal) for meal in meals]

        return SuccessResponse(
            message="Meals fetched successfully",
            data=meals,
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/report/count-by-date", response_model=SuccessResponse)
async def get_meal_counts_by_date_api(
    request: Request,
    start_date: date = Query(...),
    end_date: date = Query(...),
    meal_service: MealService = Depends(get_meal_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        if start_date > end_date:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="start_date must be before or equal to end_date",
            )

        counts = await meal_service.get_meal_counts_by_date(
            patient_id=str(current_patient.patient_id),
            start_date=start_date,
            end_date=end_date,
        )

        return SuccessResponse(
            message="Meal counts fetched successfully",
            data=counts,
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get(path="/report/day", response_model=SuccessResponse)
async def get_day_meal_report(
    request: Request,
    date: date,
    meal_report_service: MealReportService = Depends(get_meal_report_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        meal_report = await meal_report_service.fetch_daily_report(
            str(current_patient.patient_id), date
        )

        if not meal_report:
            return InQueueResponse(
                message="Report is being generated. Please check back shortly.",
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


@router.get("/report/range")
async def get_meal_reports_in_range(
    request: Request,
    start_date: date = Query(...),
    end_date: date = Query(...),
    meal_report_service: MealReportService = Depends(get_meal_report_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        # Validate date range
        if start_date > end_date:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Invalid date range",
                detail="Start date cannot be after end date",
            )

        reports = await meal_report_service.fetch_daily_reports_in_range(
            str(current_patient.patient_id), start_date, end_date
        )

        return SuccessResponse(
            message=f"Successfully fetched reports from {start_date} to {end_date}",
            data=reports,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
