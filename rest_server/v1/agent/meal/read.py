from uuid import UUID

from fastapi import Depends, HTTPException, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_agent_meal_v1_service,
    get_care_provider_access_service,
)
from lib.schemas.agent_meal_v1 import MealAgentMessage, SnapshotReadResponse
from lib.services.agent_meal_v1 import AgentMealV1Service
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/snapshots/{snapshot_id}",
    response_model=SuccessResponse[SnapshotReadResponse],
)
async def get_meal_agent_snapshot(
    snapshot_id: UUID,
    service: AgentMealV1Service = Depends(get_agent_meal_v1_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.PATIENT,
            ],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
):
    try:
        snapshot = await service.fetch_snapshot(snapshot_id)
        if not snapshot:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Snapshot not found",
            )
        await resolve_patient_access(
            actor=current_actor,
            patient_id=snapshot.patient_id,
            care_provider_access_service=care_provider_access_service,
        )
        return SuccessResponse(
            message="Snapshot fetched successfully",
            data=snapshot,
        )
    except HTTPException as exc:
        raise exc
    except Exception as exc:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to fetch snapshot",
            detail=str(exc),
        )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=SuccessResponse[list[MealAgentMessage]],
)
async def get_meal_agent_conversation_messages(
    conversation_id: str,
    service: AgentMealV1Service = Depends(get_agent_meal_v1_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.PATIENT,
            ],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
):
    try:
        messages = await service.fetch_conversation_messages(conversation_id)
        if messages:
            await resolve_patient_access(
                actor=current_actor,
                patient_id=UUID(messages[0].patient_id),
                care_provider_access_service=care_provider_access_service,
            )
        return SuccessResponse(
            message="Conversation messages fetched successfully",
            data=messages,
        )
    except HTTPException as exc:
        raise exc
    except Exception as exc:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to fetch conversation messages",
            detail=str(exc),
        )
