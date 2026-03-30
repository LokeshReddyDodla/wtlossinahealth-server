"""
Patient Memories — CRUD API for patient memory management.

GET    /health-query-agent/memories?patient_id=...     — list all memories
POST   /health-query-agent/memories                    — add a memory manually
DELETE /health-query-agent/memories/{key}?patient_id=... — delete a memory
"""

from fastapi import Depends, Path, Query
from pydantic import BaseModel, Field

from lib.core.constants import ProfileTypeEnum
from lib.core.container import container
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import get_care_provider_access_service
from lib.services.care_provider_access_service import CareProviderAccessService
from rest_server.response_models import SuccessResponse

from .router import router
from .utils import parse_patient_uuid


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class MemoryItem(BaseModel):
    key: str
    value: str
    category: str = "other"
    source: str = "auto_extracted"
    is_permanent: bool = False
    updated_at: str | None = None


class MemoryListResponse(BaseModel):
    patient_id: str
    total: int
    memories: list[MemoryItem]


class AddMemoryRequest(BaseModel):
    patient_id: str = Field(..., description="Patient ID")
    key: str = Field(..., max_length=100, pattern=r"^[a-z0-9_]+$", description="Memory key (e.g. 'dietary_preference')")
    value: str = Field(..., max_length=2000, description="Memory value (e.g. 'vegetarian')")


class DeleteMemoryResponse(BaseModel):
    deleted: bool
    key: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/memories", response_model=SuccessResponse[MemoryListResponse])
async def list_memories(
    patient_id: str = Query(..., description="Patient ID"),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN],
            check_permissions=False,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """List all memories for a patient."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=parse_patient_uuid(patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    from lib.ai_foundation.memory.mongo_store import MongoMemoryStore
    memory: MongoMemoryStore = container.resolve(MongoMemoryStore)
    facts = await memory.get_patient_facts(str(verified_pid))

    items = [
        MemoryItem(
            key=f.key,
            value=str(f.value),
            category=getattr(f, "category", "other") or "other",
            source=getattr(f, "source", "auto_extracted") or "auto_extracted",
            is_permanent=getattr(f, "is_permanent", False),
            updated_at=str(f.updated_at) if f.updated_at else None,
        )
        for f in facts
    ]

    return SuccessResponse(
        message=f"{len(items)} memories found",
        data=MemoryListResponse(patient_id=str(verified_pid), total=len(items), memories=items),
    )


@router.post("/memories", response_model=SuccessResponse[MemoryItem])
async def add_memory(
    payload: AddMemoryRequest,
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN],
            check_permissions=False,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Manually add a memory for a patient."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=parse_patient_uuid(payload.patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    from lib.ai_foundation.memory.base import MemoryFact, MemorySource
    from lib.ai_foundation.memory.mongo_store import MongoMemoryStore
    from lib.ai_foundation.agents.core.fact_extractor import CANONICAL_MEMORY_KEYS

    key = payload.key.strip().lower().replace(" ", "_")
    meta = CANONICAL_MEMORY_KEYS.get(key, {"category": "other", "permanent": False})

    fact = MemoryFact(
        key=key,
        value=payload.value.strip(),
        category=meta["category"],
        source=MemorySource.USER_EXPLICIT.value,
        confidence=1.0,
        is_permanent=meta["permanent"],
    )

    memory: MongoMemoryStore = container.resolve(MongoMemoryStore)
    await memory.upsert_patient_facts(str(verified_pid), [fact])

    return SuccessResponse(
        message=f"Memory '{key}' saved",
        data=MemoryItem(
            key=key,
            value=payload.value.strip(),
            category=meta["category"],
            source=MemorySource.USER_EXPLICIT.value,
            is_permanent=meta["permanent"],
        ),
    )


@router.delete("/memories/{key}", response_model=SuccessResponse[DeleteMemoryResponse])
async def delete_memory(
    key: str = Path(..., pattern=r"^[a-z0-9_]+$", description="Memory key to delete"),
    patient_id: str = Query(..., description="Patient ID"),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN],
            check_permissions=False,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Delete a specific memory by key."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=parse_patient_uuid(patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    from lib.ai_foundation.memory.mongo_store import MongoMemoryStore
    memory: MongoMemoryStore = container.resolve(MongoMemoryStore)
    deleted = await memory.delete_patient_fact(str(verified_pid), key)

    return SuccessResponse(
        message=f"Memory '{key}' deleted" if deleted else f"Memory '{key}' not found",
        data=DeleteMemoryResponse(deleted=deleted, key=key),
    )
