import traceback
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (get_fitness_report_service,
                                                   get_fitness_stats_processor,
                                                   get_glucose_stats_processor,
                                                   get_meal_stats_processor)
from lib.models.patient import Patient
from lib.schemas.glucose_stats import GlucoseLevelStats
from lib.services.fitness_report_service import FitnessReportService
from lib.utils.date.periods import OverallPeriod
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.glucose.processor import GlucoseStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.meals.processor import MealStatsProcessor
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.get(path="/stats", response_model=SuccessResponse)
async def get_patient_overview_api(
    request: Request,
    date: date = Query(...),
    meal_stats_processor: MealStatsProcessor = Depends(
        get_meal_stats_processor
    ),
    fitness_report_service: FitnessReportService = Depends(
        get_fitness_report_service
    ),
    glucose_stats_processor: GlucoseStatsProcessor = Depends(
        get_glucose_stats_processor
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        from_date = datetime.combine(date, time.min)  # Start of the day
        to_date = datetime.combine(date, time.max)  # End of the day
        patient_id = str(current_patient.patient_id)

        meal_stats = await meal_stats_processor.get_meal_report_by_date(
            patient_id, date
        )

        fitness_stats = fitness_report_service.fetch_daily_report(
            patient_id, date
        )

        glucose_stats = await glucose_stats_processor.generate_report(
            patient_id, from_date, to_date
        )

        return SuccessResponse(
            message="Meal stats fetched successfully",
            data={
                "meal_stats": meal_stats,
                "fitness_stats": fitness_stats,
                "glucose_stats": glucose_stats["overall"],
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
