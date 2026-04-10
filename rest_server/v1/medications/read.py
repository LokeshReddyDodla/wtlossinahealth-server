"""GET /medications/{patient_id} — list and detail endpoints."""

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import Depends, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_medication_service,
)
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.medication_service import MedicationService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/{patient_id}",
    response_model=SuccessResponse,
)
async def list_medications(
    patient_id: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    medication_service: MedicationService = Depends(get_medication_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.PATIENT,
            ],
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """List medications grouped by status (active, as_needed, completed)."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    med_list = await medication_service.get_medication_list(
        patient_id=str(verified_pid),
    )

    return SuccessResponse(
        message="Medications retrieved",
        data=med_list.model_dump(mode="json"),
    )


@router.get(
    "/{patient_id}/{medication_id}",
    response_model=SuccessResponse,
)
async def get_medication(
    patient_id: str,
    medication_id: str,
    medication_service: MedicationService = Depends(get_medication_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.PATIENT,
            ],
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Get a single medication with details."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    med = await medication_service.get_medication(
        medication_id=medication_id,
        patient_id=str(verified_pid),
    )

    if not med:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Medication not found",
        )

    today = date.today()
    data = MedicationService.to_response(med, today).model_dump(mode="json")

    return SuccessResponse(
        message="Medication retrieved",
        data=data,
    )
