import traceback
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (get_fitness_report_service,
                                                   get_glucose_stats_processor,
                                                   get_meal_report_service)
from lib.models.patient import Patient
from lib.services.fitness_report_service import FitnessReportService
from lib.services.meal_report_service import MealReportService
from lib.utils.glucose.processor import GlucoseStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(path="/stats", response_model=SuccessResponse)
async def get_patient_overview_api(
    request: Request,
    date: date = Query(...),
    meal_report_service: MealReportService = Depends(get_meal_report_service),
    fitness_report_service: FitnessReportService = Depends(
        get_fitness_report_service
    ),
    glucose_stats_processor: GlucoseStatsProcessor = Depends(
        get_glucose_stats_processor
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        start_date = datetime.combine(date, time.min)  # Start of the day
        end_date = datetime.combine(date, time.max)  # End of the day
        patient_id = str(current_patient.patient_id)

        meal_report = meal_report_service.fetch_daily_report(patient_id, date)

        fitness_report = fitness_report_service.fetch_daily_report(
            patient_id, date
        )

        glucose_report = await glucose_stats_processor.generate_report(
            patient_id, start_date, end_date
        )

        return SuccessResponse(
            message="Patient stats fetched successfully",
            data={
                "meal_report": meal_report,
                "fitness_report": fitness_report,
                "glucose_report": glucose_report["overall"],
            },
        )

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        error_message = f"Exception occurred: {str(e)}"
        traceback_message = traceback.format_exc()
        print("🚀 ~ error_message:", error_message)
        print("🚀 ~ traceback_message:", traceback_message)

        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
