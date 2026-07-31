"""Medication slot schedule.

Patient-local hour → the gamification ``DailyTask.task_type`` scheduled at that
hour. Single source of truth for the reminder cron.
"""

from __future__ import annotations

MEDICATION_SLOTS: dict[int, str] = {
    10: "TAKE_MEDICATION_MORNING",
    15: "TAKE_MEDICATION_AFTERNOON",
    21: "TAKE_MEDICATION_EVENING",
    23: "TAKE_MEDICATION_NIGHT",
}
