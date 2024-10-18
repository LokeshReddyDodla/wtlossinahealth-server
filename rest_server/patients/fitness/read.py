from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_fitness_processor
from lib.models.patient import Patient
from lib.schemas.fitness_stats import (FitnessDailyStats, FitnessMonthlyStats,
                                       FitnessWeeklyStats)
from lib.utils.date_utils import (get_month_start_end,
                                  get_week_start_end_by_week_no)
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.fitness.queries import (generate_all_available_dates,
                                       generate_all_available_months,
                                       generate_all_available_weeks,
                                       generate_available_data_range_by_date)
from rest_server.patients.fitness.api_schema import FitnessStatsResponse
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/stats",
    response_model=FitnessStatsResponse,
)
async def get_fitness_stats(
    request: Request,
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    fitness_processor: FitnessStatsProcessor = Depends(get_fitness_processor),
):
    try:
        from_date_str = from_date.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = to_date.strftime("%Y-%m-%dT%H:%M:%S")

        stats = fitness_processor.fetch_monthly_stats(
            from_date_str, to_date_str
        )
        return FitnessStatsResponse(
            message="Fitness stats fetched successfully",
            data=stats,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/stats/day",
)
async def get_fitness_day_stats(
    request: Request,
    date: date = Query(...),
    fitness_processor: FitnessStatsProcessor = Depends(get_fitness_processor),
):
    try:
        from_date_str = f"{date}T00:00:00"
        to_date_str = f"{date}T23:59:59"

        stats = fitness_processor.fetch_daily_stats(
            from_date_str, to_date_str, include_hourly_stats=True
        )
        return SuccessResponse(
            message="Fitness stats fetched successfully",
            data=stats[0] if len(stats) else None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/stats/week",
)
async def get_fitness_week_stats(
    request: Request,
    year: int,
    week_no: int,
    fitness_processor: FitnessStatsProcessor = Depends(get_fitness_processor),
):
    try:
        week_start, week_end = get_week_start_end_by_week_no(year, week_no)

        from_date_str = f"{week_start}T00:00:00"
        to_date_str = f"{week_end}T23:59:59"

        stats = fitness_processor.fetch_weekly_stats(
            from_date_str, to_date_str, include_daily_stats=True
        )
        return SuccessResponse(
            message="Fitness stats fetched successfully",
            data=stats[0] if len(stats) else None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/stats/month",
)
async def get_fitness_month_stats(
    request: Request,
    year: int,
    month_no: int,
    fitness_processor: FitnessStatsProcessor = Depends(get_fitness_processor),
):
    try:
        month_start, month_end = get_month_start_end(year, month_no)

        from_date_str = month_start.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = month_end.strftime("%Y-%m-%dT%H:%M:%S")

        stats = fitness_processor.fetch_monthly_stats(
            from_date_str, to_date_str, include_daily_stats=True
        )
        return SuccessResponse(
            message="Fitness stats fetched successfully",
            data=stats[0] if len(stats) else None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
