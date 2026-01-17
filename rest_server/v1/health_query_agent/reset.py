from fastapi import Depends

from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_health_query_agent_service
from lib.core.constants import ProfileTypeEnum
from lib.services.health_query_agent.service import HealthQueryAgentService
from rest_server.response_models import SuccessResponse

from .router import router


@router.post(
    "/reset",
    response_model=SuccessResponse[dict],
)
async def reset_conversation(
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
    """Reset user's conversation (clear active state)."""
    user_id = str(current_actor.user_id)
    thread_id = f"user_{user_id}"
    await agent_service.reset_conversation(thread_id=thread_id, user_id=user_id)

    return SuccessResponse(
        message="Conversation reset successfully",
        data={"user_id": user_id},
    )
