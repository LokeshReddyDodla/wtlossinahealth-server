"""Nightly plan status reconciliation.

An ACTIVE plan whose end_date has passed must become EXPIRED so retrieval —
which trusts plan_status to decide the current plan — stops surfacing it.
update_status never touches end_date, so nothing else closes this gap. Expiry
also re-vectorizes the plan, syncing plan_status into Qdrant.
"""

from __future__ import annotations

import logging
from typing import Any

from lib.workers.tasks.base import TaskResult, task_with_logging

logger = logging.getLogger(__name__)


@task_with_logging
async def reconcile_plan_statuses(ctx: dict[str, Any]) -> TaskResult:
    """Expire ended ACTIVE diet + fitness plans and re-vectorize them."""
    from lib.dependencies.service_dependencies import (
        get_patient_diet_plan_service,
        get_patient_fitness_plan_service,
    )

    diet_expired = await get_patient_diet_plan_service().expire_ended_plans()
    fitness_expired = await get_patient_fitness_plan_service().expire_ended_plans()

    logger.info(
        "plan reconciliation: expired %d diet + %d fitness plans",
        diet_expired, fitness_expired,
    )
    return TaskResult(
        success=True,
        data={"diet_expired": diet_expired, "fitness_expired": fitness_expired},
    )
