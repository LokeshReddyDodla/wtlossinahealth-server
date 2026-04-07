"""DELETE /prescriptions/{patient_id}/{prescription_id} — archive a prescription."""

from fastapi import Depends, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_medication_service
from lib.services.medication_service import MedicationService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.delete(
    "/{patient_id}/{prescription_id}",
    response_model=SuccessResponse,
)
async def archive_prescription(
    patient_id: str,
    prescription_id: str,
    medication_service: MedicationService = Depends(get_medication_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.DELETE,
        )
    ),
):
    """Archive a prescription (soft delete)."""
    prescription = await medication_service.archive_prescription(
        prescription_id=prescription_id,
    )

    if not prescription:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Prescription not found",
        )

    return SuccessResponse(message="Prescription archived")
