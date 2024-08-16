import traceback
from typing import Union
from datetime import datetime, timedelta
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select

from sqlalchemy.orm import selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient


from lib.schemas.fitness import FitnessStatsResponse
from lib.utils.cgm_utils import CGMDataUtils
from lib.utils.date.periods import DayWisePeriod, OverallPeriod, WeekWisePeriod

from lib.utils.fitness.processor import FitnessDataProcessor
from lib.utils.glucose.processor import PeriodicStatsProcessor


from rest_server.cgm.api_schema import (
    GlucoseReportResponse,
)
from rest_server.response_models import ErrorResponse

# Create FastAPI router
router = APIRouter(prefix="/fitness/report")


@router.get(
    "/detailed_fitness_report",
    tags=["Fitness"],
    response_model=FitnessStatsResponse,
)
async def get_fitness_data(
    request: Request,
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    current_patient: Patient = Depends(get_current_patient),
) -> Union[FitnessStatsResponse, Exception]:
    try:
        clickhouse_store = request.state.context.clickhouse_store
        patient_id = str(current_patient.patient_id)

        processor = FitnessDataProcessor(clickhouse_store, patient_id)

        from_date_str = from_date.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = to_date.strftime("%Y-%m-%dT%H:%M:%S")

        summary_stats = processor.fetch_summary_stats(
            from_date_str, to_date_str
        )
        daily_stats = processor.fetch_daily_stats(from_date_str, to_date_str)
        weekly_stats = processor.fetch_weekly_stats(from_date_str, to_date_str)
        monthly_stats = processor.fetch_monthly_stats(
            from_date_str, to_date_str
        )
        hourly_stats = processor.fetch_hourly_stats(from_date_str, to_date_str)

        return FitnessStatsResponse(
            patient_id=str(current_patient.patient_id),
            summary=summary_stats,
            daily_stats=daily_stats,
            weekly_stats=weekly_stats,
            monthly_stats=monthly_stats,
            hourly_stats=hourly_stats,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        error_message = f"Exception occurred: {str(e)}"
        traceback_message = traceback.format_exc()
        print("🚀 ~ error_message:", error_message)
        print("🚀 ~ traceback_message:", traceback_message)
        response = {"message": "Internal Server Error", "detail": str(e)}
        raise HTTPException(status_code=500, detail=response)
