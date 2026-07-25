import logging
import time as _time
from uuid import UUID

from fastapi import HTTPException

from lib.ai_foundation.agents.state import RequestPriority
from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor

logger = logging.getLogger(__name__)


def parse_patient_uuid(patient_id: str) -> UUID:
    """Parse a patient_id string into a UUID, raising HTTP 400 on failure."""
    try:
        return UUID(patient_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid patient ID format — expected UUID") from exc


def resolve_priority(role: ProfileTypeEnum) -> RequestPriority:
    """Map actor role to request priority (also drives rate-limit quotas)."""
    if role == ProfileTypeEnum.ADMIN:
        return RequestPriority.CRITICAL
    if role == ProfileTypeEnum.CARE_PROVIDER:
        return RequestPriority.HIGH
    return RequestPriority.NORMAL


async def enforce_rate_limit(current_actor: Actor, priority: RequestPriority | None = None) -> None:
    """Check the per-actor rate limit and raise 429 if exceeded.

    Fail-open on limiter errors (availability over enforcement) —
    consistent with the RateLimiter itself.
    """
    if priority is None:
        priority = resolve_priority(current_actor.role)
    try:
        from lib.core.container import container
        from lib.ai_foundation.rate_limit.limiter import RateLimiter

        limiter: RateLimiter = container.resolve(RateLimiter)
        result = await limiter.check_and_record(current_actor.id, priority)
        if not result.allowed:
            retry_after = max(1, int(result.reset_at - _time.time()))
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Limit: {result.limit}/hour. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Rate limiter unavailable, allowing request: %s", exc)


def resolve_bot_conversation_id(actor_type, actor_id, subject_patient_id=None):
    if actor_type == "patient":
        return f"bot:patient:{actor_id}"

    if actor_type == "care_provider" and subject_patient_id:
        return f"bot:provider:{actor_id}:patient:{subject_patient_id}"

    if actor_type == "care_provider":
        return f"bot:provider:{actor_id}"

    # Fallback for other actor types (e.g., admin)
    return f"bot:{actor_type}:{actor_id}"
