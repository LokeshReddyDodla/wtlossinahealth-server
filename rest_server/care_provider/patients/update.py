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


@router.post("/assign", response_model=SuccessResponse)
async def assign_care_provider_to_patient(
    patient_id: str,
    assigned_care_provider_id: str,
    patient_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE, CareProviderFeature.PATIENTS
        )
    ),
):
    updated_patient = await patient_service.assign_care_provider_to_patient(
        current_care_provider=current_care_provider,
        patient_id=patient_id,
        assigned_care_provider_id=assigned_care_provider_id,
    )

    return SuccessResponse(
        message="Care provider assigned to patient successfully.",
        data={"patient_id": str(updated_patient.patient_id)},
    )
