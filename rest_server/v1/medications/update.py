"""PATCH /medications/{patient_id}/{medication_id}/* — lifecycle actions."""

from datetime import date
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


@router.patch(
    "/{patient_id}/{medication_id}/discontinue",
    response_model=SuccessResponse,
)
async def discontinue_medication(
    patient_id: str,
    medication_id: str,
    medication_service: MedicationService = Depends(get_medication_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.UPDATE,
        )
    ),
):
    """Discontinue a medication. Tasks will stop generating."""
    med = await medication_service.discontinue_medication(
        medication_id=medication_id,
        discontinued_by=str(current_actor.id),
    )

    if not med:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Medication not found",
        )

    return SuccessResponse(message="Medication discontinued")


@router.patch(
    "/{patient_id}/{medication_id}/pause",
    response_model=SuccessResponse,
)
async def pause_medication(
    patient_id: str,
    medication_id: str,
    medication_service: MedicationService = Depends(get_medication_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.UPDATE,
        )
    ),
):
    """Pause a medication temporarily. Tasks will stop generating."""
    med = await medication_service.pause_medication(
        medication_id=medication_id,
    )

    if not med:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Medication not found",
        )

    return SuccessResponse(message="Medication paused")


@router.patch(
    "/{patient_id}/{medication_id}/resume",
    response_model=SuccessResponse,
)
async def resume_medication(
    patient_id: str,
    medication_id: str,
    medication_service: MedicationService = Depends(get_medication_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.UPDATE,
        )
    ),
):
    """Resume a paused medication. Tasks will start generating again."""
    med = await medication_service.resume_medication(
        medication_id=medication_id,
    )

    if not med:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Medication not found",
        )

    return SuccessResponse(message="Medication resumed")
