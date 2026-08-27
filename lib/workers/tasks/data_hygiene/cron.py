from lib.workers.tasks.data_hygiene.tasks import (
    clear_stale_pregnancies,
    sync_diabetes_duration,
    expire_stale_care_intents,
    mark_stale_connected_apps,
)
from lib.workers.tasks.utils.cron_helpers import daily_cron, weekly_cron


def get_cron_jobs():
    return [
        weekly_cron(
            coroutine=clear_stale_pregnancies,
            name="clear-stale-pregnancies",
            weekday=1,
            hour=2,
            minute=0,
            timeout_s=300,
        ),
        daily_cron(
            coroutine=sync_diabetes_duration,
            name="sync-diabetes-duration",
            hour=3,
            minute=0,
            timeout_s=300,
        ),
        daily_cron(
            coroutine=expire_stale_care_intents,
            name="expire-stale-care-intents",
            hour=1,
            minute=0,
            timeout_s=300,
        ),
        weekly_cron(
            coroutine=mark_stale_connected_apps,
            name="mark-stale-connected-apps",
            weekday=1,
            hour=2,
            minute=30,
            timeout_s=300,
        ),
    ]
