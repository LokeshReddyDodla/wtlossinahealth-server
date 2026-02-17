"""ARQ task entry points for the weightloss agentic loop."""

from __future__ import annotations

from typing import Any, Dict, List
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from lib.workers.tasks.base import task_with_logging


@task_with_logging
async def run_agentic_cycle(ctx: Dict[str, Any], user_id: str) -> None:
    from lib.dependencies.service_dependencies import (
        get_agentic_orchestrator_service,
    )

    orchestrator = get_agentic_orchestrator_service()
    await orchestrator.run_weekly_cycle(UUID(user_id))


@task_with_logging
async def schedule_daily_agentic_cycles(ctx: Dict[str, Any]) -> None:
    """
    Enumerate all active weightloss enrollments and queue the async agentic
    loop for each user. Runs from ARQ cron at midnight IST.
    """
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.weight_loss_agent import WeightLossAgentEnrollment
    from lib.workers.arq.redis import enqueue_job

    store = container.resolve(PostgresStore)
    async with store.get_session() as session:
        result = await session.execute(
            select(WeightLossAgentEnrollment.patient_id).where(
                WeightLossAgentEnrollment.is_active.is_(True)
            )
        )
        patient_ids: List[UUID] = list(result.scalars().all())

    for patient_id in patient_ids:
        await enqueue_job("run_agentic_cycle", str(patient_id))

    logger.info(
        f"✅ Scheduled agentic cycles for {len(patient_ids)} active enrollments"
    )
