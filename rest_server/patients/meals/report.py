import traceback
from typing import Union
from datetime import datetime, timedelta
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Query


from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient


from lib.schemas.fitness_stats import (
    CompleteFitnessReport,
)

from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.meals.processor import MealStatsProcessor
from rest_server.patients.fitness.api_schema import FitnessReportResponse
from .router import router


@router.get(
    "/report",
)
async def get_meal_report(
    request: Request,
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        clickhouse_store = request.state.context.clickhouse_store
        patient_id = str(current_patient.patient_id)

        async with request.state.context.postgres_store.get_session() as session:

            processor = MealStatsProcessor(
                session, clickhouse_store, patient_id
            )

            grouped_by_date = await processor.fetch_meals_grouped_by_date(
                from_date, to_date
            )

        return grouped_by_date
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        error_message = f"Exception occurred: {str(e)}"
        traceback_message = traceback.format_exc()
        print("🚀 ~ error_message:", error_message)
        print("🚀 ~ traceback_message:", traceback_message)
        response = {"message": "Internal Server Error", "detail": str(e)}
        raise HTTPException(status_code=500, detail=response)
