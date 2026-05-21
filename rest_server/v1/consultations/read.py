"""GET /consultations/{patient_id} — list and detail endpoints."""

from uuid import UUID

from fastapi import Depends, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_consultation_service,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.consultation_service import ConsultationService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/{patient_id}",
    response_model=SuccessResponse,
)
async def list_consultations(
    patient_id: str,
    consultation_service: ConsultationService = Depends(get_consultation_service),
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
    """List all consultations for a patient (newest first)."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    items = await consultation_service.list_for_patient(
        patient_id=str(verified_pid),
    )

    return SuccessResponse(
        message="Consultations retrieved",
        data=[item.model_dump(mode="json") for item in items],
    )


@router.get(
    "/{patient_id}/{consultation_id}",
    response_model=SuccessResponse,
)
async def get_consultation(
    patient_id: str,
    consultation_id: str,
    consultation_service: ConsultationService = Depends(get_consultation_service),
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
    """Get a single consultation including transcript and structured insights."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    consultation = await consultation_service.get(
        patient_id=str(verified_pid),
        consultation_id=consultation_id,
    )
    if not consultation:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Consultation not found",
        )

    return SuccessResponse(
        message="Consultation retrieved",
        data=consultation.model_dump(mode="json"),
    )
