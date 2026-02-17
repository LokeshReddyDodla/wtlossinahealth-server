"""HTTP endpoint exposing the safety rules engine."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_plan_composer_service,
    get_safety_rules_service,
)
from lib.schemas.weightloss_agent.safety import (
    SafetyValidationRequest,
    SafetyValidationResponse,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.weightloss_agent.safety_rules_service import (
    SafetyRulesService,
)
from lib.services.weightloss_agent.plan_composer_service import (
    PlanComposerService,
)
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from rest_server.response_models import SuccessResponse

router = APIRouter(prefix="/safety", tags=["Safety"])


@router.post(
    "/validate",
    response_model=SuccessResponse[SafetyValidationResponse],
    status_code=status.HTTP_200_OK,
)
async def validate_safety_rules(
    payload: SafetyValidationRequest,
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    safety_rules_service: SafetyRulesService = Depends(
        get_safety_rules_service
    ),
    plan_service: PlanComposerService = Depends(
        get_plan_composer_service
    ),
) -> SuccessResponse[SafetyValidationResponse]:
    patient_id = await resolve_patient_access(
        actor=actor,
        patient_id=payload.user_id,
        care_provider_access_service=care_provider_access_service,
    )
    payload.user_id = patient_id
    stored_context = await plan_service.get_context_snapshot(
        payload.user_id
    )

    def merge(stored: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
        base = stored or {}
        extra = incoming or {}
        return {**base, **extra}

    merged_context = {
        "user_id": str(payload.user_id),
        "medications": payload.medications,
        "conditions": merge(
            stored_context.get("conditions"), payload.conditions
        ),
        "inbody": merge(stored_context.get("inbody"), payload.inbody),
        "fitness": merge(stored_context.get("fitness"), payload.fitness),
        "willingness": merge(
            stored_context.get("willingness"), payload.willingness
        ),
    }

    result = await safety_rules_service.evaluate(
        merged_context
    )
    response = SafetyValidationResponse(**result)
    return SuccessResponse(
        message="Safety rules evaluated",
        data=response,
    )
