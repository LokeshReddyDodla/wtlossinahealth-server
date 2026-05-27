from fastapi import Depends, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_patient_smbg_service
from lib.models.patient import Patient
from lib.schemas.patient_smbg import PatientSMBG as PatientSMBGSchema
from lib.schemas.patient_smbg import PatientSMBGCreate
from lib.services.patient_smbg_service import PatientSmbgService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/upload", response_model=SuccessResponse)
async def upload_smbg(
    request: Request,
    smbg_data: PatientSMBGCreate,
    patient_smbg_service: PatientSmbgService = Depends(get_patient_smbg_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        new_smbg = await patient_smbg_service.upload_patient_smbg(
            str(current_patient.patient_id), smbg_data
        )

        smbg = PatientSMBGSchema.model_validate(new_smbg)

        return SuccessResponse(
            message="SMBG data uploaded successfully.",
            data={
                "smbg_data": smbg,
            },
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
