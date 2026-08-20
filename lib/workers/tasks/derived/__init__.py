"""Derived-data engine drain task."""

from lib.workers.tasks.derived.refresh import refresh_patient

__all__ = ["refresh_patient", "get_tasks", "get_cron_jobs"]


def get_tasks():
    from arq.worker import func

    # keep_result=0 lets the stable per-patient _job_id re-enqueue back-to-back;
    # a kept result key would block the next kick. Nothing awaits this result.
    return [func(refresh_patient, name="refresh_patient", keep_result=0)]


def get_cron_jobs():
    # Deliberately none — the engine is activity-driven (patient uploads mark
    # cells; provider panel views refresh stale rows). See spec §6.
    return []
