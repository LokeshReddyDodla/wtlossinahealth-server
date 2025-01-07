import traceback
import uuid
from datetime import date, datetime, time, timedelta
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_glucose_stats_processor
from lib.models.patient import Patient
from lib.utils.date.periods import OverallPeriod
from lib.utils.glucose.processor import GlucoseStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/stats/day", response_model=SuccessResponse)
async def get_fitness_day_stats(
    request: Request,
    date: date = Query(...),
    glucose_stats_processor: GlucoseStatsProcessor = Depends(
        get_glucose_stats_processor
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        from_date = datetime.combine(date, time.min)  # Start of the day
        to_date = datetime.combine(date, time.max)  # End of the day

        glucose_stats = await glucose_stats_processor.generate_report(
            str(current_patient.patient_id), from_date, to_date
        )

        return SuccessResponse(
            message="Fitness stats fetched successfully",
            data=glucose_stats["overall"],
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
