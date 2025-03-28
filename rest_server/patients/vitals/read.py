
from fastapi import Depends, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_patient_vital_service
from lib.models.patient import Patient
from lib.schemas.patient_vital import PatientVital as PatientVitalSchema
from lib.services.patient_vital_service import PatientVitalService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def get_patient_vitals(
    request: Request,
    patient_vital_service: PatientVitalService = Depends(
        get_patient_vital_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        vital_records = await patient_vital_service.get_patient_vitals(
            str(current_patient.patient_id)
        )

        vitals = [
            PatientVitalSchema.model_validate(record)
            for record in vital_records
        ]
        return SuccessResponse(
            message="Vitals fetched successfully.",
            data=vitals,
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
