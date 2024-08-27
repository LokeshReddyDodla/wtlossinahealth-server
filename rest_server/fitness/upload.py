from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)
from loguru import logger
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient
from lib.services.fitness_upload_service import FitnessUploadService
from rest_server.fitness.api_schema import FitnessDataRequest
from rest_server.response_models import SuccessResponse, ErrorResponse
from typing import List, Union


router = APIRouter(prefix="/patient/fitness")


@router.post("/upload", tags=["Fitness"])
async def upload_fitness_data(
    request: Request,
    fitness_data: FitnessDataRequest,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
    try:
        clickhouse_store = request.state.context.clickhouse_store
        postgres_store = request.state.context.postgres_store

        async with postgres_store.get_session() as postgres_session:
            fitness_service = FitnessUploadService(
                clickhouse_store,
                postgres_session,
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
        await postgres_session.rollback()
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
