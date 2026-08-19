"""Patient panel materialization tasks."""

from lib.workers.tasks.patient_panel.recompute import (
    recompute_patient_panel,
    reconcile_patient_panel,
)

__all__ = [
    "recompute_patient_panel",
    "reconcile_patient_panel",
    "get_tasks",
    "get_cron_jobs",
]


def get_tasks():
    from arq.worker import func

    # keep_result=0 lets the stable per-patient _job_id re-enqueue each cycle;
    # a kept result key would block it. Nothing awaits this result.
    return [
        func(recompute_patient_panel, name="recompute_patient_panel", keep_result=0),
        reconcile_patient_panel,
    ]


def get_cron_jobs():
    from lib.workers.tasks.utils.cron_helpers import interval_cron

    return [
        interval_cron(
            coroutine=reconcile_patient_panel,
            name="patient-panel-reconcile",
            minute_step=30,
            timeout_s=300,
        ),
    ]
