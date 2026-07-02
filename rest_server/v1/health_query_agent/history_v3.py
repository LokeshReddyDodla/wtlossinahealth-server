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

import re
from datetime import datetime
from fastapi import Depends, Query, HTTPException
from pydantic import BaseModel, Field

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import (
    get_memory_store,
    get_patient_name_resolver,
)
from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver, fallback_name
from lib.ai_foundation.memory.mongo_store import MongoMemoryStore
from lib.ai_foundation.agents.thread_utils import resolve_thread_id, thread_prefix_for_user
from rest_server.response_models import SuccessResponse

from .router import router


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


class PatientInfo(BaseModel):
    patient_id: str
    name: str
    profile_picture: str | None = None


class ThreadInfo(BaseModel):
    thread_id: str
    title: str | None = None
    patients: list[PatientInfo] = Field(default_factory=list)
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
    thread_id: str | None = Query(
        None,
        description="Thread ID — required for providers/admins (from /history/v3/threads), "
        "optional for patients (auto-resolved to their single thread)",
    ),
    limit: int = Query(50, ge=1, le=500, description="Number of turns to return"),
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
    memory: MongoMemoryStore = Depends(get_memory_store),
):
    """Retrieve conversation turns for a thread.

    Patients: thread_id is optional — auto-resolved to bot:patient:{patient_id}.
    Providers/Admins: thread_id required (GET /history/v3/threads → pick → pass here).

    Security: users can only access threads that belong to them
    (thread_id starts with their role:id prefix). Admin can access any thread.
    """
    # Auto-resolve thread_id for patients
    if thread_id is None:
        if current_actor.role == ProfileTypeEnum.PATIENT:
            thread_id = resolve_thread_id(
                role="patient", actor_id=current_actor.id,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="thread_id is required for care providers and admins",
            )

    resolved_thread_id: str = thread_id

    # Security: verify the thread belongs to this user (or user is admin)
    if current_actor.role != ProfileTypeEnum.ADMIN:
        expected_prefix = thread_prefix_for_user(
            role=current_actor.role.value, actor_id=current_actor.id,
        )
        if not resolved_thread_id.startswith(expected_prefix):
            raise HTTPException(status_code=403, detail="Access denied to this thread")

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
    memory: MongoMemoryStore = Depends(get_memory_store),
    resolver: PatientNameResolver = Depends(get_patient_name_resolver),
):
    """List all conversation threads for the current user.

    No params needed — threads are scoped to the authenticated user automatically.
    """
    collection = memory.get_collection("ai_conversation_turns")

    prefix = thread_prefix_for_user(role=current_actor.role.value, actor_id=current_actor.id)
    match_filter = {"thread_id": {"$regex": f"^{re.escape(prefix)}"}}

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

    # Fetch titles + patient_ids from thread summaries
    summaries_collection = memory.get_collection("ai_thread_summaries")
    thread_ids = [r["thread_id"] for r in thread_rows]
    title_map: dict[str, str] = {}
    patient_ids_map: dict[str, list[str]] = {}

    if thread_ids:
        summary_cursor = summaries_collection.find(
            {"thread_id": {"$in": thread_ids}},
            {"thread_id": 1, "title": 1, "patient_ids": 1, "_id": 0},
        )
        async for s in summary_cursor:
            if s.get("title"):
                title_map[s["thread_id"]] = s["title"]
            if s.get("patient_ids"):
                patient_ids_map[s["thread_id"]] = s["patient_ids"]

    # Resolve patient profiles (names + pics) for all unique patient IDs
    all_patient_ids = set()
    for pids in patient_ids_map.values():
        all_patient_ids.update(pids)

    patient_profiles: dict[str, PatientInfo] = {}
    if all_patient_ids:
        try:
            profiles = await resolver.resolve_profiles(list(all_patient_ids))
            for p in profiles:
                patient_profiles[p.patient_id] = PatientInfo(
                    patient_id=p.patient_id, name=p.name, profile_picture=p.profile_picture,
                )
        except Exception:
            for pid in all_patient_ids:
                patient_profiles[pid] = PatientInfo(patient_id=pid, name=fallback_name(pid))

    threads = [
        ThreadInfo(
            thread_id=r["thread_id"],
            title=title_map.get(r["thread_id"]),
            patients=[
                patient_profiles.get(pid, PatientInfo(patient_id=pid, name=fallback_name(pid)))
                for pid in patient_ids_map.get(r["thread_id"], [])
            ],
            turn_count=r["turn_count"],
            last_turn=r["last_turn"],
        )
        for r in thread_rows
    ]

    return SuccessResponse(
        message="Threads retrieved successfully",
        data=ThreadListResponse(threads=threads, total=len(threads)),
    )
