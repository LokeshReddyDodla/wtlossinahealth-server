"""Patient export tasks."""

from lib.workers.tasks.patient_export.tasks import (
    cleanup_expired_patient_exports,
    export_patient_data,
)

__all__ = [
    "export_patient_data",
    "cleanup_expired_patient_exports",
    "get_tasks",
    "get_cron_jobs",
]


def get_tasks():
    return [
        export_patient_data,
        cleanup_expired_patient_exports,
    ]


def get_cron_jobs():
    from lib.workers.tasks.patient_export.cron import (
        get_cron_jobs as _get_cron_jobs,
    )

    return _get_cron_jobs()
