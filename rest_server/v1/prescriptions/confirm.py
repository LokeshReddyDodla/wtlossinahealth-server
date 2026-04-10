"""POST /prescriptions/{patient_id}/confirm — confirm a draft or create new prescription + medications."""

from uuid import UUID

from fastapi import Depends

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_medication_service,
)
from lib.schemas.medication import ConfirmPrescriptionRequest
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.medication_service import MedicationService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
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
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Confirm a prescription and create active medications. CP only."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    prescription = await medication_service.confirm_prescription(
        patient_id=str(verified_pid),
        data=payload,
    )

    return SuccessResponse(
        message="Prescription confirmed and medications created",
        data={"prescription_id": str(prescription.prescription_id)},
    )
