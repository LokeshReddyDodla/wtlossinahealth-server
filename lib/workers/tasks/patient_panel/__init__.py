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
    from arq.cron import CronJob

    # Full-roster reconcile every 3h (00:00, 03:00, … 21:00). The 30-min sweep
    # starved the Postgres pool; the panel's freshness label makes a 3h staleness
    # visible to the care provider. Per-patient _job_id dedupes an overrun sweep.
    return [
        CronJob(
            coroutine=reconcile_patient_panel,
            name="patient-panel-reconcile",
            month=None,
            day=None,
            weekday=None,
            hour=set(range(0, 24, 3)),
            minute={0},
            second={0},
            microsecond=0,
            unique=True,
            job_id="patient-panel-reconcile",
            timeout_s=300,
            keep_result_s=0,
            keep_result_forever=False,
            max_tries=1,
            run_at_startup=False,
        ),
    ]
