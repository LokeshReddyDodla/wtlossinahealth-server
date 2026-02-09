"""Celery task entry points for weightloss agentic chat flows."""

from __future__ import annotations

import asyncio
from typing import List
from uuid import UUID

from celery import shared_task
from sqlalchemy import select


@shared_task
async def run_weightloss_agentic_for_user(user_id: str) -> None:
    from lib.dependencies.service_dependencies import get_agentic_chat_service

    service = get_agentic_chat_service()
    await service.run_scheduled_for_user(UUID(user_id))


@shared_task
def schedule_weightloss_agentic_flows() -> None:
    """Enumerate all active weightloss enrollments and queue agentic chat flows."""

    async def _fetch_active_patient_ids() -> List[UUID]:
        from lib.core.container import container
        from lib.core.postgres_store import PostgresStore
        from lib.models.weight_loss_agent import WeightLossAgentEnrollment

        store = container.resolve(PostgresStore)
        async with store.get_session() as session:
            result = await session.execute(
                select(WeightLossAgentEnrollment.patient_id).where(
                    WeightLossAgentEnrollment.is_active.is_(True)
                )
            )
            return list(result.scalars().all())

    patient_ids = asyncio.run(_fetch_active_patient_ids())
    for patient_id in patient_ids:
        run_weightloss_agentic_for_user.delay(str(patient_id))
