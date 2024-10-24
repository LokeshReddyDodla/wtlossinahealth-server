from typing import List, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient
from lib.services.fitness_upload_service import FitnessUploadService
from rest_server.patients.fitness.api_schema import FitnessDataRequest
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post(
    "/upload",
    response_model=SuccessResponse,
)
async def upload_fitness_data(
    request: Request,
    fitness_data: FitnessDataRequest,
    session: AsyncSession = Depends(get_postgres_session),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        clickhouse_store = request.state.context.clickhouse_store
        fitness_sync_store = request.app.state.fitness_sync_store

        fitness_service = FitnessUploadService(
            clickhouse_store,
            fitness_sync_store,
            session,
            str(current_patient.patient_id),
        )
        last_sync_time = await fitness_service.process_fitness_data(
            fitness_data
        )

        return SuccessResponse(
            message="Fitness data uploaded and stored successfully.",
            data={"last_sync_timestamp": last_sync_time},
        )
    except Exception as e:
        await session.rollback()
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
