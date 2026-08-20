"""Per-patient drain for the derived-data engine (spec: docs/derived-data-spec.md §4)."""

from __future__ import annotations

from datetime import date
from typing import Any

from lib.derived.dirty import _RE_ENQUEUE_DEFER_S, enqueue_refresh_patient, get_dirty_store
from lib.derived.registry import DataDomain, get_report_domains
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def refresh_patient(ctx: dict[str, Any], patient_id: str) -> TaskResult:
    from lib.core.container import container
    from lib.services.patient_panel.service import PatientPanelService

    store = get_dirty_store()
    claim_ts, cells = await store.claim(patient_id)

    # Registered domains recompute their dirty days here; unregistered ones
    # still regenerate via legacy upload-path triggers until they migrate in.
    # A failure raises before the clear, so cells survive for the arq retry.
    domains = get_report_domains()
    days_computed = 0
    for cell in sorted(cells, key=lambda c: (c["domain"], c["date"])):
        impl = domains.get(DataDomain(cell["domain"]))
        if impl is None:
            continue
        await impl.compute_daily(patient_id, date.fromisoformat(cell["date"]))
        days_computed += 1

    # Finalizers run once, after every domain is fresh. An empty claim is the
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
            "days_computed": days_computed,
            "assessment": signal.assessment.value if signal else None,
        },
    )
