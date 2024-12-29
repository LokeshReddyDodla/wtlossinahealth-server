from fastapi import Depends, HTTPException, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_care_provider_profile_service, get_health_facility_service,
    get_patient_profile_service)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.care_provider_permissions import (CareProviderFeature,
                                                 CareProviderPermissionAction)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.delete("/remove", response_model=SuccessResponse)
async def remove_care_provider_from_patient(
    patient_id: str,
    care_provider_id: str,
    care_provider_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.DELETE, CareProviderFeature.PATIENTS
        )
    ),
):
    await care_provider_service.remove_patient_from_care_provider(
        care_provider_id=care_provider_id,
        patient_id=patient_id,
    )

    return SuccessResponse(
        message="Care provider removed from patient successfully.",
        data={"patient_id": patient_id, "care_provider_id": care_provider_id},
    )
