from fastapi import Depends, File, Request, UploadFile, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_cgm_service
from lib.models.patient import Patient
from lib.services.cgm_upload_service import CGMUploadService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/upload/libreview-raw-csv", response_model=SuccessResponse)
async def upload_libreview_raw_csv(
    request: Request,
    file: UploadFile = File(...),
    cgm_upload_service: CGMUploadService = Depends(get_cgm_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        await cgm_upload_service.parse_and_upload_libreview_raw_csv_data(
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


@router.post("/upload/linx-raw-csv", response_model=SuccessResponse)
async def upload_linx_raw_csv(
    request: Request,
    file: UploadFile = File(...),
    cgm_upload_service: CGMUploadService = Depends(get_cgm_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        await cgm_upload_service.parse_and_upload_linx_csv_data(
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
