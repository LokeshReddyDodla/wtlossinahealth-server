from fastapi import FastAPI, HTTPException
from datetime import date, datetime
from typing import List, Optional
from lib.schemas.fitness_stats import (
    FitnessDailyStats,
    FitnessWeeklyStats,
    FitnessMonthlyStats,
)
from lib.utils.date_utils import (
    get_month_start_end,
    get_week_start_end_by_week_no,
)
from lib.utils.fitness.processor import FitnessStatsProcessor

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient

from fastapi import APIRouter, Depends, HTTPException, Request, Query

from lib.utils.fitness.queries import (
    generate_all_available_dates,
    generate_all_available_months,
    generate_all_available_weeks,
    generate_available_data_range_by_date,
)
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
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        clickhouse_store = request.state.context.clickhouse_store
        patient_id = str(current_patient.patient_id)

        processor = FitnessStatsProcessor(clickhouse_store, patient_id)

        from_date_str = from_date.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = to_date.strftime("%Y-%m-%dT%H:%M:%S")

        stats = processor.fetch_monthly_stats(from_date_str, to_date_str)
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
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        clickhouse_store = request.state.context.clickhouse_store
        patient_id = str(current_patient.patient_id)

        processor = FitnessStatsProcessor(clickhouse_store, patient_id)

        from_date_str = f"{date}T00:00:00"
        to_date_str = f"{date}T23:59:59"

        stats = processor.fetch_daily_stats(
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
    week_no: int,
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        clickhouse_store = request.state.context.clickhouse_store
        patient_id = str(current_patient.patient_id)

        processor = FitnessStatsProcessor(clickhouse_store, patient_id)

        week_start, week_end = get_week_start_end_by_week_no(2024, week_no)

        from_date_str = week_start.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = week_end.strftime("%Y-%m-%dT%H:%M:%S")

        stats = processor.fetch_weekly_stats(
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
    month_no: int,
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        clickhouse_store = request.state.context.clickhouse_store
        patient_id = str(current_patient.patient_id)

        processor = FitnessStatsProcessor(clickhouse_store, patient_id)

        month_start, month_end = get_month_start_end(2024, month_no)

        from_date_str = month_start.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = month_end.strftime("%Y-%m-%dT%H:%M:%S")

        stats = processor.fetch_monthly_stats(
            from_date_str, to_date_str, include_daily_stats=True
        )
        return SuccessResponse(
            message="Fitness stats fetched successfully",
            data=stats[0] if len(stats) else None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
