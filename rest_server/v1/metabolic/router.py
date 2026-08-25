"""Read-only metabolic engine surface for the dashboard.

The engine owns BMIQ and the metabolic risk profile — a derived, cross-domain
score (body composition + profile + weight trend + flags). This exposes it
read-only so any surface (body-composition tab, progress, day) reads one source
rather than recomputing it.
"""

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_metabolic_service,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from rest_server.response_models import SuccessResponse

if TYPE_CHECKING:
    from lib.ai_foundation.clinical.metabolic.service import MetabolicService

router = APIRouter(
    prefix="/patients/{patient_id}/metabolic",
    tags=["Metabolic"],
)


@router.get("/risk-profile", response_model=SuccessResponse)
async def get_metabolic_risk_profile(
    patient_id: UUID,
    service: "MetabolicService" = Depends(get_metabolic_service),
    actor: Actor = Depends(
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
    access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    resolved_patient_id = await resolve_patient_access(
        actor=actor,
        patient_id=patient_id,
        care_provider_access_service=access_service,
    )
    profile = await service.risk_profile(str(resolved_patient_id))
    return SuccessResponse(
        message="Metabolic risk profile retrieved", data=profile
    )
