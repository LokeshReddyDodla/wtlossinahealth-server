"""Materialize the patient_panel_signal read model.

`recompute_patient_panel` is the unit of work (one patient → one upserted row);
`reconcile_patient_panel` is the sweep that enumerates the roster and fans out a
recompute per patient. The sweep alone keeps the whole panel — including
disengaged / data-gap patients, which a provider most needs to see — materialized
on a cadence; event-driven recompute can enqueue the same unit for freshness.

Recompute is idempotent (single upsert), so overlapping fan-out and re-runs are
safe, and a source failure degrades one patient's row without failing the sweep.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy.future import select

from lib.dependencies.database import postgres_store
from lib.models.patient import Patient
from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging

_BATCH = 500


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


@task_with_logging
async def reconcile_patient_panel(ctx: dict[str, Any]) -> TaskResult:
    """Enumerate the roster in pages and enqueue a recompute per patient."""
    enqueued = 0
    last_id: str | None = None
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
                _job_id=f"panel:recompute:{pid}",
                _queue_name=Queues.REPORTS,
            )
            enqueued += 1
        last_id = ids[-1]

    logger.info(f"[reconcile_patient_panel] enqueued {enqueued} recomputes")
    return TaskResult(success=True, data={"enqueued": enqueued})
