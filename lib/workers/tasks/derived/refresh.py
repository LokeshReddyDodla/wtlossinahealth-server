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
    known = {d.value: d for d in DataDomain}
    days_by_domain: dict[DataDomain, list[date]] = {}
    for cell in cells:
        # A cell holding a retired domain value must not poison the drain —
        # it still gets cleared below with the rest of the claim.
        domain = known.get(cell["domain"])
        if domain is None:
            continue
        days_by_domain.setdefault(domain, []).append(date.fromisoformat(cell["date"]))

    days_computed = 0
    for domain in sorted(days_by_domain, key=lambda d: d.value):
        impl = domains.get(domain)
        if impl is None:
            continue
        days = sorted(set(days_by_domain[domain]))
        compute_days = getattr(impl, "compute_days", None)
        if compute_days is not None:
            # batch hook: for domains whose inputs are fetched per window
            await compute_days(patient_id, days)
            days_computed += len(days)
        else:
            for day in days:
                await impl.compute_daily(patient_id, day)
                days_computed += 1
        rollup = getattr(impl, "rollup", None)
        if rollup is not None:
            await rollup(patient_id, days)
        vectorize = getattr(impl, "vectorize", None)
        if vectorize is not None:
            await vectorize(patient_id, days)

    # Finalizers run once, after every domain is fresh. An empty claim is the
    # provider-view stale-refresh path: recompute time-based transitions
    # (lapsed / data-gap) that no upload event can ever trigger.
    signal = await container.resolve(PatientPanelService).recompute(patient_id)

    # Unregistered domains' cells are cleared too — they are kicks for the
    # finalizers, not a banked backlog; a domain migrating in later needs its
    # own backfill.
    await store.clear(patient_id, cells, claim_ts)
    if await store.has_dirty(patient_id):
        # arq drops a duplicate _job_id while that job is in flight — this run
        # may BE the immediate or the deferred job, so the re-kick rides its
        # own id, which can never be the one currently executing.
        await enqueue_refresh_patient(patient_id, defer_s=_RE_ENQUEUE_DEFER_S, rekick=True)

    return TaskResult(
        success=True,
        data={
            "patient_id": patient_id,
            "cells_drained": len(cells),
            "days_computed": days_computed,
            "assessment": signal.assessment.value if signal else None,
        },
    )
