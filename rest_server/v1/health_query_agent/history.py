from fastapi import Depends, Query
from typing import Optional
from datetime import datetime

from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_health_query_agent_service
from lib.core.constants import ProfileTypeEnum
from lib.services.health_query_agent.service import HealthQueryAgentService
from rest_server.response_models import SuccessResponse

from .router import router
from .api_schema import ConversationHistoryResponse


@router.get(
    "/history",
    response_model=SuccessResponse[ConversationHistoryResponse],
)
async def get_conversation_history(
    limit: int = Query(100, ge=1, le=1000, description="Number of messages to return"),
    offset: int = Query(0, ge=0, description="Number of messages to skip"),
    since: Optional[datetime] = Query(
        None, description="Only return messages after this timestamp"
    ),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.PATIENT,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
        )
    ),
    agent_service: HealthQueryAgentService = Depends(get_health_query_agent_service),
):
    user_id = str(current_actor.user_id)

    history = await agent_service.get_conversation_history(
        user_id=user_id,
        limit=limit,
        offset=offset,
        since=since,
    )

    return SuccessResponse(
        message="History retrieved successfully",
        data=history,
    )
