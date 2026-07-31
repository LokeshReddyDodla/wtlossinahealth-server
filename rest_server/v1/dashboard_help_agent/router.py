"""
Dashboard Help — in-product helpline endpoint for care providers and admins.

Answers "how do I… / where is…" questions about using the dashboard and returns a
matching how-to video when one exists.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status

from lib.ai_foundation.agents.dashboard_help import DashboardHelpAgent
from lib.core.constants import AIFeatureEnum
from lib.services.ai_feature_toggle_service import ai_feature_toggle_service
from lib.ai_foundation.agents.state import AgentContext, AgentInput
from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.base import get_current_user
from lib.utils.http_exceptions import raise_http_exception

from .api_schema import DashboardHelpRequest, DashboardHelpResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard-help", tags=["Dashboard Help"])

_ALLOWED_ROLES = {ProfileTypeEnum.CARE_PROVIDER.value, ProfileTypeEnum.ADMIN.value}


async def require_care_provider_or_admin(
    user_role: tuple = Depends(get_current_user),
) -> tuple[str, str]:
    """Allow only care providers and admins."""
    user_id, role = user_role
    if role not in _ALLOWED_ROLES:
        raise_http_exception(
            status_code=status.HTTP_403_FORBIDDEN,
            message="Access denied. This help assistant is for care providers and admins.",
        )
    return user_id, role


def _get_agent() -> DashboardHelpAgent:
    from lib.core.container import container

    return container.resolve(DashboardHelpAgent)


@router.post("/chat", response_model=DashboardHelpResponse)
async def dashboard_help_chat(
    payload: DashboardHelpRequest,
    agent: Annotated[DashboardHelpAgent, Depends(_get_agent)],
    user: Annotated[tuple, Depends(require_care_provider_or_admin)],
) -> DashboardHelpResponse:
    """Answer a dashboard how-to question, with a matching video when one fits."""
    user_id, role = user
    await ai_feature_toggle_service.require_system(AIFeatureEnum.DASHBOARD_HELP)
    agent_input = AgentInput(
        message=payload.message,
        context=AgentContext(user_id=user_id, user_role=role),
        metadata={"history": [turn.model_dump() for turn in payload.history]},
    )

    output = await agent.run(agent_input)
    data = output.data or {}
    return DashboardHelpResponse(
        reply=output.message,
        video_url=data.get("video_url"),
        video_id=data.get("video_id"),
        trace_id=output.trace_id,
    )
