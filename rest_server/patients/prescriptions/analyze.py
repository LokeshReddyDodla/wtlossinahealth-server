import json

from fastapi import Depends, HTTPException, Request, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_prescription_analysis_service,
    get_prescription_service,
)
from lib.models.patient import Patient
from lib.schemas.patient_prescription import PatientPrescriptionRead
from lib.schemas.patient_prescription_analysis import (
    PrescriptionAnalysisResponse,
)
from lib.services.prescription_analysis_service import (
    PrescriptionAnalysisService,
)
from lib.services.prescription_service import PrescriptionService
from lib.utils.http_exceptions import raise_http_exception


from rest_server.response_models import SuccessResponse

from .router import router


@router.post(path="/analyze", response_model=SuccessResponse)
async def analyze_prescription_api(
    request: Request,
    image_url: str,
    prescription_service: PrescriptionService = Depends(
        get_prescription_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        response = await prescription_service.upload_and_analyze_prescription(
            image_url, str(current_patient.patient_id)
        )

        return SuccessResponse(
            message="Prescription analyzed successfully.",
            data={
                "prescription_data": PatientPrescriptionRead.model_validate(
                    response
                ),
                "ai_response_generated": True,
            },
        )

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Prescription analysis failed. Please try again later.",
            detail=str(e),
        )
