import traceback
import uuid
from datetime import datetime, timedelta
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import get_meal_stats_processor
from lib.models.patient import Patient
from lib.schemas.fitness_stats import CompleteFitnessReport
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.meals.processor import MealStatsProcessor
from rest_server.patients.fitness.api_schema import FitnessReportResponse
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/report")
async def get_meal_report(
    request: Request,
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    meal_stats_processor: MealStatsProcessor = Depends(
        get_meal_stats_processor
    ),
):
    try:
        grouped_by_date = await meal_stats_processor.get_meal_stats_by_date(
            from_date, to_date
        )

        return grouped_by_date
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
