
from fastapi import Depends, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_fitness_upload_service
from lib.models.patient import Patient
from lib.services.fitness_upload_service import FitnessUploadService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.patients.fitness.api_schema import FitnessDataRequest
from rest_server.response_models import SuccessResponse

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
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        last_sync_time = await fitness_upload_service.process_fitness_data(
            str(current_patient.patient_id), fitness_data
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
