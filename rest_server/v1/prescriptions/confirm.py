"""POST /prescriptions/{patient_id}/confirm — confirm a draft or create new prescription + medications."""

from fastapi import Depends, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_medication_service
from lib.schemas.medication import ConfirmPrescriptionRequest
from lib.services.medication_service import MedicationService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.post(
    "/{patient_id}/confirm",
    response_model=SuccessResponse,
)
async def confirm_prescription(
    patient_id: str,
    payload: ConfirmPrescriptionRequest,
    medication_service: MedicationService = Depends(get_medication_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.CREATE,
        )
    ),
):
    """Confirm a prescription and create active medications. CP only."""
    try:
        prescription = await medication_service.confirm_prescription(
            patient_id=patient_id,
            data=payload,
        )

        return SuccessResponse(
            message="Prescription confirmed and medications created",
            data={"prescription_id": str(prescription.prescription_id)},
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to confirm prescription",
            detail=str(e),
        )
