"""POST /prescriptions/{patient_id}/safety-check — run the AI safety co-signer
over a set of medicines before they're issued. Read-only; no persistence."""

from uuid import UUID

from fastapi import Depends

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_prescription_safety_service,
)
from lib.schemas.prescription_safety import PrescriptionSafetyRequest
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.prescription_safety_service import PrescriptionSafetyService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/{patient_id}/safety-check", response_model=SuccessResponse)
async def safety_check(
    patient_id: str,
    payload: PrescriptionSafetyRequest,
    safety_service: PrescriptionSafetyService = Depends(get_prescription_safety_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.ADMIN, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Check drug interactions, duplicate therapy, and allergy conflicts. CP only."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )
    result = await safety_service.check(str(verified_pid), payload.medicines)
    return SuccessResponse(message="Safety check complete", data=result.model_dump())
