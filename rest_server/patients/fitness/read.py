from fastapi import FastAPI, HTTPException
from datetime import datetime
from typing import List, Optional
from lib.schemas.fitness import (
    FitnessDailyStats,
    FitnessWeeklyStats,
    FitnessMonthlyStats,
)
from lib.utils.fitness.processor import FitnessDataProcessor

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


router = APIRouter()


@router.get(
    "/stats",
    tags=["Fitness"],
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

        processor = FitnessDataProcessor(clickhouse_store, patient_id)

        from_date_str = from_date.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = to_date.strftime("%Y-%m-%dT%H:%M:%S")

        stats = processor.fetch_monthly_stats(from_date_str, to_date_str)
        return FitnessStatsResponse(
            message="Fitness stats fetched successfully",
            data=stats,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
