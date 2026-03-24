"""
Conversation History v3 — retrieves conversation turns from the foundation memory store.

Supports all roles:
- Patient: sees own conversations
- Care Provider: sees conversations for assigned patients
- Admin: sees conversations for any patient

Endpoints:
    GET /history/v3         — list conversation turns for a thread
    GET /history/v3/threads — list all thread IDs for the current user/patient
"""

from datetime import datetime
from typing import Optional

from fastapi import Depends, Query, HTTPException
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
from .utils import resolve_bot_conversation_id


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ConversationTurnResponse(BaseModel):
    role: str = Field(description="'user' or 'assistant'")
    content: str
    agent_id: str = ""
    timestamp: datetime
    metadata: dict | None = None


class ConversationHistoryV3Response(BaseModel):
    thread_id: str
    total_turns: int
    turns: list[ConversationTurnResponse]


class ThreadListResponse(BaseModel):
    threads: list[dict] = Field(description="List of thread info dicts with thread_id and turn_count")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_thread_id_for_history(
    current_actor: Actor,
    patient_id: str | None,
) -> str:
    """Build the thread_id for history lookup."""
    if current_actor.role == ProfileTypeEnum.PATIENT:
        return resolve_bot_conversation_id(
            actor_type="patient",
            actor_id=current_actor.id,
        )

    # Care provider or admin querying a specific patient
    if patient_id:
        return resolve_bot_conversation_id(
            actor_type=current_actor.role.value,
            actor_id=current_actor.id,
            subject_patient_id=patient_id,
        )

    # Care provider or admin without patient_id → their own thread
    return resolve_bot_conversation_id(
        actor_type=current_actor.role.value,
        actor_id=current_actor.id,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/history/v3", response_model=SuccessResponse[ConversationHistoryV3Response])
async def get_conversation_history_v3(
    patient_id: Optional[str] = Query(None, description="Patient ID (required for care_provider, optional for admin)"),
    limit: int = Query(50, ge=1, le=500, description="Number of turns to return"),
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
    """Retrieve conversation history from the foundation memory store.

    - Patient: returns own conversation (patient_id ignored)
    - Care Provider: requires patient_id, must have access
    - Admin: optional patient_id, can see any patient
    """
    # Access control
    if current_actor.role == ProfileTypeEnum.CARE_PROVIDER:
        if not patient_id:
            raise HTTPException(status_code=400, detail="patient_id is required for care providers")
        from uuid import UUID
        accessible = await care_provider_access_service.get_accessible_patients(
            care_provider_id=UUID(current_actor.id),
            patient_ids=[UUID(patient_id)],
        )
        if not accessible:
            raise HTTPException(status_code=403, detail="No access to this patient")

    thread_id = _resolve_thread_id_for_history(current_actor, patient_id)

    memory: MongoMemoryStore = container.resolve(MongoMemoryStore)
    turns = await memory.get_thread_turns(thread_id, limit=limit)

    turn_responses = [
        ConversationTurnResponse(
            role=t.role,
            content=t.content,
            agent_id=t.agent_id,
            timestamp=t.timestamp,
            metadata=t.metadata if t.metadata else None,
        )
        for t in turns
    ]

    return SuccessResponse(
        message="History retrieved successfully",
        data=ConversationHistoryV3Response(
            thread_id=thread_id,
            total_turns=len(turn_responses),
            turns=turn_responses,
        ),
    )


@router.get("/history/v3/threads", response_model=SuccessResponse[ThreadListResponse])
async def list_conversation_threads(
    limit: int = Query(20, ge=1, le=100, description="Max threads to return"),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.PATIENT,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            check_permissions=False,
        )
    ),
):
    """List all conversation thread IDs for the current user.

    Returns thread_id and approximate turn count for each thread.
    Useful for building a conversation list UI.
    """
    memory: MongoMemoryStore = container.resolve(MongoMemoryStore)
    collection = memory._mongo.get_collection("ai_conversation_turns")

    # Build prefix for this user's threads
    if current_actor.role == ProfileTypeEnum.PATIENT:
        prefix = f"bot:patient:{current_actor.id}"
    elif current_actor.role == ProfileTypeEnum.CARE_PROVIDER:
        prefix = f"bot:provider:{current_actor.id}"
    elif current_actor.role == ProfileTypeEnum.ADMIN:
        prefix = f"bot:admin:{current_actor.id}"
    else:
        prefix = f"bot:{current_actor.role.value}:{current_actor.id}"

    # Aggregate: distinct thread_ids matching this prefix, with count
    pipeline = [
        {"$match": {"thread_id": {"$regex": f"^{prefix}"}}},
        {"$group": {
            "_id": "$thread_id",
            "turn_count": {"$sum": 1},
            "last_turn": {"$max": "$timestamp"},
        }},
        {"$sort": {"last_turn": -1}},
        {"$limit": limit},
    ]

    cursor = collection.aggregate(pipeline)
    threads = []
    async for doc in cursor:
        threads.append({
            "thread_id": doc["_id"],
            "turn_count": doc["turn_count"],
            "last_turn": doc["last_turn"].isoformat() if doc.get("last_turn") else None,
        })

    return SuccessResponse(
        message="Threads retrieved successfully",
        data=ThreadListResponse(threads=threads),
    )
