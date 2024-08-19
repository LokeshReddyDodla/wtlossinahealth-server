from fastapi import FastAPI, HTTPException
from datetime import datetime
from typing import List
from lib.schemas.fitness import (
    FitnessDailyStats,
    FitnessWeeklyStats,
    FitnessMonthlyStats,
)
from lib.utils.fitness.processor import FitnessDataProcessor

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient

from fastapi import APIRouter, Depends, HTTPException, Request, Query

from rest_server.fitness.api_schema import (
    FitnessDailyStatsResponse,
    FitnessMonthlyStatsResponse,
    FitnessWeeklyStatsResponse,
)


router = APIRouter(prefix="/fitness/stats")


@router.get(
    "/daily", tags=["Fitness"], response_model=FitnessDailyStatsResponse
)
async def get_daily_stats(
    request: Request,
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        clickhouse_store = request.state.context.clickhouse_store
        patient_id = str(current_patient.patient_id)

        processor = FitnessDataProcessor(clickhouse_store, patient_id)

        from_date_str = from_date.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = to_date.strftime("%Y-%m-%dT%H:%M:%S")

        daily_stats = processor.fetch_daily_stats(from_date_str, to_date_str)

        return FitnessDailyStatsResponse(
            message="Daily stats fetched successfully",
            data=daily_stats,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/weekly",
    tags=["Fitness"],
    response_model=FitnessWeeklyStatsResponse,
)
async def get_weekly_stats(
    request: Request,
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        clickhouse_store = request.state.context.clickhouse_store
        patient_id = str(current_patient.patient_id)

        processor = FitnessDataProcessor(clickhouse_store, patient_id)

        from_date_str = from_date.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = to_date.strftime("%Y-%m-%dT%H:%M:%S")

        weekly_stats = processor.fetch_weekly_stats(from_date_str, to_date_str)
        return FitnessWeeklyStatsResponse(
            message="Weekly stats fetched successfully",
            data=weekly_stats,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/monthly",
    tags=["Fitness"],
    response_model=FitnessMonthlyStatsResponse,
)
async def get_monthly_stats(
    request: Request,
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        clickhouse_store = request.state.context.clickhouse_store
        patient_id = str(current_patient.patient_id)

        processor = FitnessDataProcessor(clickhouse_store, patient_id)

        from_date_str = from_date.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = to_date.strftime("%Y-%m-%dT%H:%M:%S")

        monthly_stats = processor.fetch_monthly_stats(
            from_date_str, to_date_str
        )
        return FitnessMonthlyStatsResponse(
            message="Monthly stats fetched successfully",
            data=monthly_stats,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
