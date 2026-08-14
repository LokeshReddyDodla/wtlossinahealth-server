from uuid import UUID

from fastapi import Depends, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_patient_brief_service,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.patient_brief.service import PatientBriefService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


def _brief_actor():
    # Provider-facing: admin / care-provider only (patients don't see their brief).
    return get_current_actor(
        allowed_roles=[ProfileTypeEnum.ADMIN, ProfileTypeEnum.CARE_PROVIDER],
        care_provider_feature=CareProviderFeature.PATIENTS,
        care_provider_action=CareProviderPermissionAction.READ,
    )


async def _resolve(patient_id, current_actor, access_service):
    target = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id) if patient_id else None,
        care_provider_access_service=access_service,
    )
    if not target:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND, message="Patient not found"
        )
    return str(target)


@router.get("/{patient_id}/brief", response_model=SuccessResponse)
async def get_patient_brief(
    patient_id: str,
    brief_service: PatientBriefService = Depends(get_patient_brief_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    current_actor: Actor = Depends(_brief_actor()),
):
    target = await _resolve(patient_id, current_actor, care_provider_access_service)
    brief = await brief_service.get(target)
    return SuccessResponse(message="Brief retrieved successfully", data=brief)


@router.post("/{patient_id}/brief/refresh", response_model=SuccessResponse)
async def refresh_patient_brief(
    patient_id: str,
    brief_service: PatientBriefService = Depends(get_patient_brief_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    current_actor: Actor = Depends(_brief_actor()),
):
    target = await _resolve(patient_id, current_actor, care_provider_access_service)
    brief = await brief_service.refresh(target)
    return SuccessResponse(message="Brief refreshed successfully", data=brief)
