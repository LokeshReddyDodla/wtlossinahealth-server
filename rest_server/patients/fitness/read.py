from datetime import date, datetime
from typing import List, Optional

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_fitness_stats_processor
from lib.models.patient import Patient
from lib.utils.date_utils import (get_month_start_end,
                                  get_week_start_end_by_week_no)
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/stats",
    response_model=SuccessResponse,
)
async def get_fitness_stats(
    request: Request,
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    fitness_processor: FitnessStatsProcessor = Depends(
        get_fitness_stats_processor
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        from_date_str = from_date.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = to_date.strftime("%Y-%m-%dT%H:%M:%S")

        stats = fitness_processor.fetch_monthly_stats(
            str(current_patient.patient_id), from_date_str, to_date_str
        )
        return SuccessResponse(
            message="Fitness stats fetched successfully",
            data=stats,
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get(
    "/stats/day",
)
async def get_fitness_day_stats(
    request: Request,
    date: date = Query(...),
    fitness_processor: FitnessStatsProcessor = Depends(
        get_fitness_stats_processor
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        from_date_str = f"{date}T00:00:00"
        to_date_str = f"{date}T23:59:59"

        stats = fitness_processor.fetch_daily_stats(
            str(current_patient.patient_id),
            from_date_str,
            to_date_str,
            include_hourly_stats=True,
        )
        return SuccessResponse(
            message="Fitness stats fetched successfully",
            data=stats[0] if len(stats) else None,
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get(
    "/stats/week",
)
async def get_fitness_week_stats(
    request: Request,
    year: int,
    week_no: int,
    fitness_processor: FitnessStatsProcessor = Depends(
        get_fitness_stats_processor
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        week_start, week_end = get_week_start_end_by_week_no(year, week_no)

        from_date_str = f"{week_start}T00:00:00"
        to_date_str = f"{week_end}T23:59:59"

        stats = fitness_processor.fetch_weekly_stats(
            str(current_patient.patient_id),
            from_date_str,
            to_date_str,
            include_daily_stats=True,
        )
        return SuccessResponse(
            message="Fitness stats fetched successfully",
            data=stats[0] if len(stats) else None,
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get(
    "/stats/month",
)
async def get_fitness_month_stats(
    request: Request,
    year: int,
    month_no: int,
    fitness_processor: FitnessStatsProcessor = Depends(
        get_fitness_stats_processor
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        month_start, month_end = get_month_start_end(year, month_no)

        from_date_str = month_start.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = month_end.strftime("%Y-%m-%dT%H:%M:%S")

        stats = fitness_processor.fetch_monthly_stats(
            str(current_patient.patient_id),
            from_date_str,
            to_date_str,
            include_daily_stats=True,
        )
        return SuccessResponse(
            message="Fitness stats fetched successfully",
            data=stats[0] if len(stats) else None,
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
