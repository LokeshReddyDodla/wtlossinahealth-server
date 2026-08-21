"""POST /v1/admin/ops/vector-coverage-sweep — one-tap Qdrant coverage repair.

Kicks the same diff-based sweep the weekly cron runs, with a caller-chosen
window — the recovery button after an embedding outage (credits, API down).
Diff-first: only missing vectors are re-embedded, so a wide window over a
healthy roster costs reads, not embeddings.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends, Query

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.models.admin import Admin
from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job, get_arq_pool
from lib.workers.tasks.vector_coverage.sweep import SWEEP_LOCK_KEY
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/vector-coverage-sweep", response_model=SuccessResponse)
async def trigger_vector_coverage_sweep(
    window_days: int = Query(
        120,
        ge=1,
        le=3650,
        description="How far back to diff sources against Qdrant (3650 ≈ full history).",
    ),
    current_admin: Admin = Depends(get_current_admin),
) -> SuccessResponse:
    # Courtesy pre-check; the task's own lock is the authoritative guard.
    redis = await get_arq_pool()
    if await redis.exists(SWEEP_LOCK_KEY):
        return SuccessResponse(
            message="A coverage sweep is already running — not starting another",
            data={"job_id": None, "already_running": True},
        )

    job = await enqueue_job(
        "vector_coverage_sweep",
        window_days,
        None,
        _job_id=f"vector:coverage:manual:{datetime.now():%Y%m%d%H%M%S}",
        _queue_name=Queues.DEFAULT,
    )
    return SuccessResponse(
        message=f"Coverage sweep started ({window_days}d window)",
        data={"job_id": job.job_id if job else None},
    )
