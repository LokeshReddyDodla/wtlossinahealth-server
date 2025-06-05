from fastapi import Depends

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_care_provider_profile_service,
    get_patient_profile_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from rest_server.response_models import SuccessResponse

from .router import router


@router.delete("/remove", response_model=SuccessResponse)
async def remove_care_provider_from_patient(
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
    await patient_service.remove_care_providers_from_patient(
        patient_id=patient_id,
        care_provider_ids=[care_provider_id],
        health_facility_id=str(current_care_provider.health_facility_id),
    )

    return SuccessResponse(
        message="Care provider removed from patient successfully.",
        data={
            "patient_id": patient_id,
            "removed_care_provider_id": care_provider_id,
        },
    )
