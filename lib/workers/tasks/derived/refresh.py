"""Per-patient drain for the derived-data engine (spec: docs/derived-data-spec.md §4)."""

from __future__ import annotations

from typing import Any

from lib.derived.dirty import _RE_ENQUEUE_DEFER_S, enqueue_refresh_patient, get_dirty_store
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def refresh_patient(ctx: dict[str, Any], patient_id: str) -> TaskResult:
    from lib.core.container import container
    from lib.services.patient_panel.service import PatientPanelService

    store = get_dirty_store()
    claim_ts, cells = await store.claim(patient_id)

    # Report domains migrate into this drain slice by slice; until then their
    # reports regenerate via the legacy upload-path triggers and this drain
    # runs only the cross-domain finalizers. An empty claim is the
    # provider-view stale-refresh path: recompute time-based transitions
    # (lapsed / data-gap) that no upload event can ever trigger.
    signal = await container.resolve(PatientPanelService).recompute(patient_id)

    await store.clear(patient_id, cells, claim_ts)
    if await store.has_dirty(patient_id):
        # arq drops a duplicate _job_id while this run is in flight, so marks
        # that landed mid-drain must be re-kicked from here.
        await enqueue_refresh_patient(patient_id, defer_s=_RE_ENQUEUE_DEFER_S)

    return TaskResult(
        success=True,
        data={
            "patient_id": patient_id,
            "cells_drained": len(cells),
            "assessment": signal.assessment.value if signal else None,
        },
    )
