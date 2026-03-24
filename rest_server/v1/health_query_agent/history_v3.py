"""
Conversation History v3 — retrieves conversation turns from the foundation memory store.

Thread isolation:
- Patient:       bot:patient:{patient_id}                    — one thread per patient
- Care Provider: bot:provider:{provider_id}:patient:{pid}    — isolated per provider per patient
- Admin:         bot:admin:{admin_id}:patient:{pid}          — isolated per admin per patient

Endpoints:
    GET /history/v3         — get conversation turns for a thread
    GET /history/v3/threads — list threads for the current user (or all threads for a patient if admin)
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
    title: str | None = None
    total_turns: int
    turns: list[ConversationTurnResponse]


class ThreadInfo(BaseModel):
    thread_id: str
    title: str | None = None
    turn_count: int
    last_turn: str | None = None


class ThreadListResponse(BaseModel):
    threads: list[ThreadInfo]
    total: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/history/v3", response_model=SuccessResponse[ConversationHistoryV3Response])
async def get_conversation_history_v3(
    patient_id: Optional[str] = Query(None, description="Patient ID (required for care_provider, optional for admin)"),
    thread_id: Optional[str] = Query(None, description="Direct thread_id override (admin only)"),
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
    """Retrieve conversation history for a thread.

    Thread resolution:
    - Patient: automatically resolves to the patient's own thread
    - Care Provider: requires patient_id → resolves to provider's thread for that patient
    - Admin: can use patient_id (own thread with that patient) OR thread_id (view any thread)
    """
    resolved_thread_id: str

    if thread_id and current_actor.role == ProfileTypeEnum.ADMIN:
        # Admin can directly view any thread
        resolved_thread_id = thread_id
    elif current_actor.role == ProfileTypeEnum.PATIENT:
        resolved_thread_id = resolve_bot_conversation_id(
            actor_type="patient", actor_id=current_actor.id,
        )
    elif current_actor.role == ProfileTypeEnum.CARE_PROVIDER:
        if not patient_id:
            raise HTTPException(status_code=400, detail="patient_id is required for care providers")
        # Validate access
        from uuid import UUID
        accessible = await care_provider_access_service.get_accessible_patients(
            care_provider_id=UUID(current_actor.id),
            patient_ids=[UUID(patient_id)],
        )
        if not accessible:
            raise HTTPException(status_code=403, detail="No access to this patient")
        resolved_thread_id = resolve_bot_conversation_id(
            actor_type="care_provider", actor_id=current_actor.id,
            subject_patient_id=patient_id,
        )
    elif current_actor.role == ProfileTypeEnum.ADMIN:
        if patient_id:
            resolved_thread_id = resolve_bot_conversation_id(
                actor_type="admin", actor_id=current_actor.id,
                subject_patient_id=patient_id,
            )
        else:
            resolved_thread_id = resolve_bot_conversation_id(
                actor_type="admin", actor_id=current_actor.id,
            )
    else:
        raise HTTPException(status_code=403, detail="Unsupported role")

    memory: MongoMemoryStore = container.resolve(MongoMemoryStore)
    turns = await memory.get_thread_turns(resolved_thread_id, limit=limit)

    # Fetch title from thread summary
    thread_summary = await memory.get_thread_summary(resolved_thread_id)
    title = thread_summary.title if thread_summary and thread_summary.title else None

    return SuccessResponse(
        message="History retrieved successfully",
        data=ConversationHistoryV3Response(
            thread_id=resolved_thread_id,
            title=title,
            total_turns=len(turns),
            turns=[
                ConversationTurnResponse(
                    role=t.role, content=t.content, agent_id=t.agent_id,
                    timestamp=t.timestamp, metadata=t.metadata or None,
                )
                for t in turns
            ],
        ),
    )


@router.get("/history/v3/threads", response_model=SuccessResponse[ThreadListResponse])
async def list_conversation_threads(
    patient_id: Optional[str] = Query(None, description="Admin only: list ALL threads for a patient (across all providers)"),
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
    """List conversation threads.

    - Patient: all their threads
    - Care Provider: all their patient threads
    - Admin: their own threads OR (with patient_id) all threads for a patient across all providers
    """
    memory: MongoMemoryStore = container.resolve(MongoMemoryStore)
    collection = memory._mongo.get_collection("ai_conversation_turns")

    if current_actor.role == ProfileTypeEnum.ADMIN and patient_id:
        # Admin asking "show me all conversations about patient X"
        # Matches: bot:*:patient:{patient_id} across all providers/admins
        match_filter = {"thread_id": {"$regex": f":patient:{patient_id}$"}}
    elif current_actor.role == ProfileTypeEnum.PATIENT:
        match_filter = {"thread_id": {"$regex": f"^bot:patient:{current_actor.id}"}}
    elif current_actor.role == ProfileTypeEnum.CARE_PROVIDER:
        match_filter = {"thread_id": {"$regex": f"^bot:provider:{current_actor.id}"}}
    elif current_actor.role == ProfileTypeEnum.ADMIN:
        match_filter = {"thread_id": {"$regex": f"^bot:admin:{current_actor.id}"}}
    else:
        match_filter = {"thread_id": {"$regex": f"^bot:{current_actor.role.value}:{current_actor.id}"}}

    pipeline = [
        {"$match": match_filter},
        {"$group": {
            "_id": "$thread_id",
            "turn_count": {"$sum": 1},
            "last_turn": {"$max": "$timestamp"},
        }},
        {"$sort": {"last_turn": -1}},
        {"$limit": limit},
    ]

    cursor = collection.aggregate(pipeline)
    thread_rows = []
    async for doc in cursor:
        thread_rows.append({
            "thread_id": doc["_id"],
            "turn_count": doc["turn_count"],
            "last_turn": str(doc["last_turn"]) if doc.get("last_turn") else None,
        })

    # Fetch titles from thread summaries
    summaries_collection = memory._mongo.get_collection("ai_thread_summaries")
    thread_ids = [r["thread_id"] for r in thread_rows]
    title_map: dict[str, str] = {}
    if thread_ids:
        summary_cursor = summaries_collection.find(
            {"thread_id": {"$in": thread_ids}},
            {"thread_id": 1, "title": 1, "_id": 0},
        )
        async for s in summary_cursor:
            if s.get("title"):
                title_map[s["thread_id"]] = s["title"]

    threads = [
        ThreadInfo(
            thread_id=r["thread_id"],
            title=title_map.get(r["thread_id"]),
            turn_count=r["turn_count"],
            last_turn=r["last_turn"],
        )
        for r in thread_rows
    ]

    return SuccessResponse(
        message="Threads retrieved successfully",
        data=ThreadListResponse(threads=threads, total=len(threads)),
    )
