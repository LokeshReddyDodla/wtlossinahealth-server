from fastapi import Depends

from lib.core.constants import AIFeatureEnum
from lib.dependencies.auth.admin_auth import get_current_admin
from lib.models.admin import Admin
from lib.services.ai_feature_toggle_service import ai_feature_toggle_service
from rest_server.response_models import SuccessResponse

from .router import router

_LABELS: dict[AIFeatureEnum, str] = {
    AIFeatureEnum.HEALTH_CHAT: "Health chat (patient assistant)",
    AIFeatureEnum.VOICE: "Voice assistant",
    AIFeatureEnum.MEAL_ANALYSIS: "Meal analysis",
    AIFeatureEnum.PROACTIVE: "Proactive notifications",
    AIFeatureEnum.DASHBOARD_HELP: "Dashboard help (provider)",
    AIFeatureEnum.COHORT_AGENT: "Cohort agent (provider)",
    AIFeatureEnum.RESEARCH_AGENT: "Research agent (provider)",
    AIFeatureEnum.PRODUCT_BOT: "Product bot (public, system-only)",
    AIFeatureEnum.SUPPORT_ASSISTANT: "Support assistant (patient tickets)",
}

# product_bot has no patient/facility, so a facility-scoped pause is meaningless.
_SYSTEM_ONLY = {AIFeatureEnum.PRODUCT_BOT.value}


@router.get("", response_model=SuccessResponse)
async def get_ai_feature_state(
    current_admin: Admin = Depends(get_current_admin),
) -> SuccessResponse:
    overrides = await ai_feature_toggle_service.get_overrides()
    features = [
        {
            "key": feature.value,
            "label": _LABELS[feature],
            "system_only": feature.value in _SYSTEM_ONLY,
        }
        for feature in AIFeatureEnum
    ]
    return SuccessResponse(
        message="AI feature state fetched successfully",
        data={"features": features, "overrides": overrides},
    )
