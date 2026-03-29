"""
Reset v3 — clear a conversation thread in the foundation memory store.

Deletes all turns and the thread summary for a given thread. The next
query will start a fresh conversation.
"""

import logging
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from lib.core.constants import ProfileTypeEnum
from lib.core.container import container
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_care_provider_access_service
from lib.ai_foundation.memory.mongo_store import MongoMemoryStore
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from rest_server.response_models import SuccessResponse

from .router import router


class ResetRequest(BaseModel):
    patient_ids: Optional[list[str]] = Field(
        None,
        description="Patient IDs to identify the thread. Same logic as /query/v3.",
    )


class ResetResponse(BaseModel):
    thread_id: str
    turns_deleted: int
    summary_deleted: bool


@router.post("/reset/v3", response_model=SuccessResponse[ResetResponse])
async def reset_conversation_v3(
    payload: ResetRequest,
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.PATIENT,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Reset a conversation thread — deletes all turns and summary.

    Thread resolution uses the same logic as /query/v3:
    - Patient: resets own thread (patient_ids ignored)
    - Care Provider: requires patient_ids to identify which thread
    - Admin: patient_ids to identify thread, or empty to reset general thread
    """
    # Resolve patient_ids (same validation as query)
    from rest_server.v1.utils import resolve_patient_ids_for_query
    resolved_patient_ids = await resolve_patient_ids_for_query(
        current_actor=current_actor,
        provided_patient_ids=payload.patient_ids,
        care_provider_access_service=care_provider_access_service,
    )

    # Resolve thread_id (same logic as query)
    from rest_server.v1.health_query_agent.query_v3 import _resolve_thread_id
    thread_id = _resolve_thread_id(current_actor, resolved_patient_ids)

    # Delete turns and summary
    memory: MongoMemoryStore = container.resolve(MongoMemoryStore)

    turns_collection = memory.get_collection("ai_conversation_turns")
    result = await turns_collection.delete_many({"thread_id": thread_id})
    turns_deleted = result.deleted_count

    summaries_collection = memory.get_collection("ai_thread_summaries")
    summary_result = await summaries_collection.delete_one({"thread_id": thread_id})
    summary_deleted = summary_result.deleted_count > 0

    logging.getLogger(__name__).info(
        "Conversation reset: actor=%s thread=%s turns_deleted=%d",
        current_actor.id, thread_id, turns_deleted,
    )

    return SuccessResponse(
        message="Conversation reset successfully",
        data=ResetResponse(
            thread_id=thread_id,
            turns_deleted=turns_deleted,
            summary_deleted=summary_deleted,
        ),
    )
