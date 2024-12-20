from fastapi import Depends, File, Request, UploadFile, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_cgm_service
from lib.models.patient import Patient
from lib.services.cgm_service import CGMService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/upload", response_model=SuccessResponse)
async def upload_cgm_data(
    request: Request,
    file: UploadFile = File(...),
    cgm_service: CGMService = Depends(get_cgm_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:

        await cgm_service.parse_and_upload_cgm_data(
            patient_id=str(current_patient.patient_id),
            file_contents=await file.read(),
        )

        return SuccessResponse(
            message="CGM data uploaded and stored successfully."
        )

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
