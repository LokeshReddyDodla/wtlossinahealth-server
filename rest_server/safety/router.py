"""HTTP endpoint exposing the safety rules engine."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, status

from lib.dependencies.service_dependencies import (
    get_plan_composer_service,
    get_safety_rules_service,
)
from lib.schemas.weightloss_agent.safety import (
    SafetyValidationRequest,
    SafetyValidationResponse,
)
from lib.services.weightloss_agent.safety_rules_service import (
    SafetyRulesService,
)
from lib.services.weightloss_agent.plan_composer_service import (
    PlanComposerService,
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
    safety_rules_service: SafetyRulesService = Depends(
        get_safety_rules_service
    ),
    plan_service: PlanComposerService = Depends(
        get_plan_composer_service
    ),
) -> SuccessResponse[SafetyValidationResponse]:
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
