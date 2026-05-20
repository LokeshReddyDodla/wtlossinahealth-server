"""V1 Patient profile — self-fetch + partial-update endpoints.

GET   /v1/patients/profile   — fetch current patient's full profile
PATCH /v1/patients/profile   — partial update (chat-style onboarding flow)

PATCH semantics: same nested shape as POST /v1/patients/onboarding but every
field Optional. Sent fields overwrite, absent fields preserve, top-level
lists replace whole. profile_completion sections are recomputed server-side
from field presence — no separate finalize call needed.
"""
from fastapi import Depends, HTTPException, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_patient_profile_service
from lib.models.patient import Patient
from lib.schemas.patient import CorePatientProfile
from lib.schemas.patient_onboarding import PatientProfileUpdate
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    path="/profile",
    response_model=SuccessResponse,
)
async def get_patient_profile(
    service: PatientProfileService = Depends(get_patient_profile_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        patient = await service.fetch_patient_profile(
            patient_id=str(current_patient.patient_id),
            detailed=True,
        )
        return SuccessResponse(
            message="Patient profile fetched.",
            data=CorePatientProfile.from_orm(patient),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.patch(
    path="/profile",
    response_model=SuccessResponse,
)
async def patch_patient_profile(
    body: PatientProfileUpdate,
    service: PatientProfileService = Depends(get_patient_profile_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        updated = await service.update_patient_profile(
            patient_id=str(current_patient.patient_id),
            data=body,
        )
        return SuccessResponse(
            message="Patient profile updated.",
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
