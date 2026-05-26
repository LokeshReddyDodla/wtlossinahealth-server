"""Detect overdue PENDING medication doses for proactive monitoring.

Deterministic detection that emits *facts* — the LLM downstream produces
the patient-facing response. Shared between the gamification reminder
cron (which already iterates patients with active meds) and any other
caller that needs the same definition of "missed."
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from lib.services.clinical_constants import MEDICATION_MISSED_GRACE_HOURS
from lib.services.gamification.time_utils import local_now


# Hour (patient-local) at which each medication slot is scheduled, mapped to
# the DailyTask.task_type used by gamification. Single source of truth — the
# reminder cron and the missed-dose detector both read this.
MEDICATION_SLOTS: dict[int, str] = {
    10: "TAKE_MEDICATION_MORNING",
    15: "TAKE_MEDICATION_AFTERNOON",
    21: "TAKE_MEDICATION_EVENING",
    23: "TAKE_MEDICATION_NIGHT",
}


class MissedDose(BaseModel):
    """One overdue PENDING medication dose."""

    daily_task_id: str
    slot: str
    medication_name: str
    task_date: str  # ISO date


def _slot_label(task_type: str) -> str:
    return task_type.replace("TAKE_MEDICATION_", "").lower()


async def find_overdue_doses(
    patient_id: Any,
    tz_name: str | None,
    store: Any,
) -> list[MissedDose]:
    """Return PENDING medication tasks whose scheduled slot is past grace.

    A slot is overdue when ``now_local.hour - slot_hour >= grace`` and the
    corresponding DailyTask for the patient + today is still PENDING.
    """
    from lib.models.gamification import DailyTask
    from lib.schemas.gamification import TaskStatus

    now_local = local_now(tz_name)
    today: date = now_local.date()

    overdue_types = [
        task_type
        for hour, task_type in MEDICATION_SLOTS.items()
        if (now_local.hour - hour) >= MEDICATION_MISSED_GRACE_HOURS
    ]
    if not overdue_types:
        return []

    async with store.get_session() as session:
        result = await session.execute(
            select(DailyTask).where(
                DailyTask.patient_id == patient_id,
                DailyTask.task_date == today,
                DailyTask.task_type.in_(overdue_types),
                DailyTask.status == TaskStatus.PENDING.value,
            )
        )
        tasks = result.scalars().all()

    return [
        MissedDose(
            daily_task_id=str(task.task_id),
            slot=_slot_label(task.task_type),
            medication_name=task.description or f"{_slot_label(task.task_type)} medication",
            task_date=today.isoformat(),
        )
        for task in tasks
    ]
