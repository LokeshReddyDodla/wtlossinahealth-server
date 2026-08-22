"""Prescription document endpoints — store the signed PDF and deliver it to the patient."""

from uuid import UUID

from fastapi import Depends, File, UploadFile

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_medication_service,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.medication_service import MedicationService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from rest_server.response_models import SuccessResponse

from .router import router

_ISSUER_ROLES = [ProfileTypeEnum.ADMIN, ProfileTypeEnum.CARE_PROVIDER]


@router.post(
    "/{patient_id}/{prescription_id}/document",
    response_model=SuccessResponse,
)
async def store_prescription_document(
    patient_id: str,
    prescription_id: str,
    file: UploadFile = File(...),
    medication_service: MedicationService = Depends(get_medication_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=_ISSUER_ROLES,
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.CREATE,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Store the signed PDF on the prescription (called on every issue)."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    file_bytes = await file.read()
    document_url = await medication_service.store_prescription_document(
        patient_id=str(verified_pid),
        prescription_id=prescription_id,
        file_bytes=file_bytes,
        file_name=file.filename or "prescription.pdf",
    )
    return SuccessResponse(message="Prescription document stored", data={"document_url": document_url})


@router.post(
    "/{patient_id}/{prescription_id}/send",
    response_model=SuccessResponse,
)
async def send_prescription(
    patient_id: str,
    prescription_id: str,
    medication_service: MedicationService = Depends(get_medication_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=_ISSUER_ROLES,
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.CREATE,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Deliver the stored prescription document to the patient's chat (fires push)."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    document_url = await medication_service.deliver_prescription(
        patient_id=str(verified_pid),
        prescription_id=prescription_id,
        sender_id=str(current_actor.id),
    )
    return SuccessResponse(message="Prescription sent to patient", data={"document_url": document_url})
