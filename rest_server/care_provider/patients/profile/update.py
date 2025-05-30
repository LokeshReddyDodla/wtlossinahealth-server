from fastapi import Depends

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import get_patient_profile_service
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/assign", response_model=SuccessResponse)
async def assign_care_provider_to_patient(
    patient_id: str,
    care_provider_id: str,
    patient_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE, CareProviderFeature.PATIENTS
        )
    ),
):
    updated_patient = await patient_service.assign_care_providers_to_patient(
        patient_id=patient_id,
        care_provider_id=[care_provider_id],
        health_facility_id=str(current_care_provider.health_facility_id),
    )

    return SuccessResponse(
        message="Care provider assigned to patient successfully.",
        data={"patient_id": str(updated_patient.patient_id)},
    )
