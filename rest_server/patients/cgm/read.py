import traceback
import uuid
from datetime import date, datetime, time, timedelta
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from lib.dependencies.service_dependencies import get_glucose_stats_processor
from lib.utils.date.periods import OverallPeriod
from lib.utils.glucose.processor import GlucoseStatsProcessor
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/stats/day",
)
async def get_fitness_day_stats(
    request: Request,
    date: date = Query(...),
    glucose_stats_processor: GlucoseStatsProcessor = Depends(
        get_glucose_stats_processor
    ),
):
    try:
        from_date = datetime.combine(date, time.min)  # Start of the day
        to_date = datetime.combine(date, time.max)  # End of the day

        overall_period = OverallPeriod(from_date, to_date)
        glucose_stats = await glucose_stats_processor.process(
            overall_period.periods
        )

        return SuccessResponse(
            message="Fitness stats fetched successfully",
            data=glucose_stats["overall"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
