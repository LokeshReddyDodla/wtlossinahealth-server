"""LibreLinkUp follower-API live-polling tasks."""

from lib.workers.tasks.librelink_up.sync import sync_all_patients_librelink_up

__all__ = [
    "sync_all_patients_librelink_up",
    "get_tasks",
    "get_cron_jobs",
]


def get_tasks():
    return [sync_all_patients_librelink_up]


def get_cron_jobs():
    from lib.workers.tasks.librelink_up.cron import (
        get_cron_jobs as get_llu_cron_jobs,
    )

    return get_llu_cron_jobs()
