from typing import List, Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import get_fitness_upload_service
from lib.models.patient import Patient
from lib.services.fitness_upload_service import FitnessUploadService
from lib.utils.http_exceptions import raise_http_exception
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
    fitness_upload_service: FitnessUploadService = Depends(
        get_fitness_upload_service
    ),
):
    try:
        last_sync_time = await fitness_upload_service.process_fitness_data(
            fitness_data
        )

        return SuccessResponse(
            message="Fitness data uploaded and stored successfully.",
            data={"last_sync_timestamp": last_sync_time},
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
