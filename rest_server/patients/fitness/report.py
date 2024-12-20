import traceback
import uuid
from datetime import datetime, timedelta
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_fitness_stats_processor
from lib.models.patient import Patient
from lib.schemas.fitness_stats import CompleteFitnessReport
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/report",
    response_model=SuccessResponse,
)
async def get_fitness_data(
    request: Request,
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    fitness_stats_processor: FitnessStatsProcessor = Depends(
        get_fitness_stats_processor
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        from_date_str = from_date.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = to_date.strftime("%Y-%m-%dT%H:%M:%S")

        summary_stats = fitness_stats_processor.fetch_summary_stats(
            from_date_str, to_date_str
        )
        daily_stats = fitness_stats_processor.fetch_daily_stats(
            from_date_str, to_date_str
        )
        weekly_stats = fitness_stats_processor.fetch_weekly_stats(
            from_date_str, to_date_str
        )
        monthly_stats = fitness_stats_processor.fetch_monthly_stats(
            from_date_str, to_date_str
        )

        return SuccessResponse(
            message="Fitness report generated successfully.",
            data=CompleteFitnessReport(
                patient_id=str(current_patient.patient_id),
                summary=summary_stats,
                daily_stats=daily_stats,
                weekly_stats=weekly_stats,
                monthly_stats=monthly_stats,
            ),
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
