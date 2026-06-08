from fastapi import Depends, Request

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .api_schema import CohortQueryRequest, CohortQueryResponse
from .router import router


@router.post(
    "/query",
    response_model=SuccessResponse[CohortQueryResponse],
    summary="Cohort Agent query",
    description="Ask a free-form research question across the care provider's patient panel.",
)
async def cohort_query(
    payload: CohortQueryRequest,
    request: Request,
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
):
    # Forward the caller's credentials so the agent's tools hit the backend's own
    # endpoints (over loopback) scoped to this same care provider.
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else auth
    device_id = request.headers.get("x-device-id")

    # Lazy import so the app still boots if openai-agents isn't installed yet.
    try:
        from lib.ai_foundation.agents.cohort_agent import run_cohort_query  # noqa: WPS433
    except Exception as e:  # noqa: BLE001
        raise_http_exception(
            status_code=503,
            message="Cohort agent unavailable",
            detail=f"openai-agents not installed: {e}",
        )

    try:
        result = await run_cohort_query(
            token=token,
            device_id=device_id,
            message=payload.message,
            history=payload.history,
        )
    except Exception as e:  # noqa: BLE001
        raise_http_exception(
            status_code=500,
            message="Cohort agent error",
            detail=str(e),
        )

    return SuccessResponse(
        data=CohortQueryResponse(answer=result["answer"], history=result["history"]),
        message="Cohort query processed",
    )
