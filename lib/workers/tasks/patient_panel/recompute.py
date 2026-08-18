"""Materialize the patient_panel_signal read model."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy.future import select

from lib.dependencies.database import postgres_store
from lib.models.patient import Patient
from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging

_BATCH = 500
_CYCLE_SECONDS = 1800


@task_with_logging
async def recompute_patient_panel(ctx: dict[str, Any], patient_id: str) -> TaskResult:
    from lib.core.container import container
    from lib.services.patient_panel.service import PatientPanelService

    service = container.resolve(PatientPanelService)
    signal = await service.recompute(patient_id)
    return TaskResult(
        success=True,
        data={"patient_id": patient_id, "assessment": signal.assessment.value if signal else None},
    )


async def enqueue_panel_recompute(patient_id: str) -> None:
    """Fire-and-forget panel refresh for one patient (on create / data change)."""
    try:
        await enqueue_job(
            "recompute_patient_panel", patient_id, _queue_name=Queues.REPORTS
        )
    except Exception as e:
        logger.warning(f"Failed to enqueue panel recompute for {patient_id}: {e}")


@task_with_logging
async def reconcile_patient_panel(ctx: dict[str, Any]) -> TaskResult:
    """Enumerate the roster in pages and enqueue a recompute per patient."""
    enqueued = 0
    last_id: str | None = None
    cycle = int(datetime.now(timezone.utc).timestamp() // _CYCLE_SECONDS)
    while True:
        async with postgres_store.get_session() as session:
            stmt = select(Patient.patient_id).order_by(Patient.patient_id).limit(_BATCH)
            if last_id is not None:
                stmt = stmt.where(Patient.patient_id > last_id)
            ids = [str(pid) for pid in (await session.execute(stmt)).scalars().all()]
        if not ids:
            break
        for pid in ids:
            await enqueue_job(
                "recompute_patient_panel",
                pid,
                _job_id=f"panel:recompute:{pid}:{cycle}",
                _queue_name=Queues.REPORTS,
            )
            enqueued += 1
        last_id = ids[-1]

    logger.info(f"[reconcile_patient_panel] enqueued {enqueued} recomputes")
    return TaskResult(success=True, data={"enqueued": enqueued})
