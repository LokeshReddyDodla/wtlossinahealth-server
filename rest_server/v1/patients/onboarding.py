"""V1 Patient onboarding — single bundled endpoint.

Replaces the legacy three-call flow (PUT /patient/profile/basic,
PATCH /patient/profile/lifestyle, PATCH /patient/profile/medical_history)
with one atomic transaction.
"""
from fastapi import Depends, HTTPException, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_patient_profile_service
from lib.models.patient import Patient
from lib.schemas.patient import CorePatientProfile
from lib.schemas.patient_onboarding import PatientOnboardingRequest
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post(
    path="/onboarding",
    response_model=SuccessResponse,
)
async def complete_patient_onboarding(
    body: PatientOnboardingRequest,
    service: PatientProfileService = Depends(get_patient_profile_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        updated = await service.complete_onboarding(
            patient_id=str(current_patient.patient_id),
            data=body,
        )
        return SuccessResponse(
            message="Patient onboarding completed.",
            data=CorePatientProfile.from_orm(updated),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
