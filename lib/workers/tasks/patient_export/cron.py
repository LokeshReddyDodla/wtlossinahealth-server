from lib.workers.tasks.patient_export.tasks import cleanup_expired_patient_exports
from lib.workers.tasks.utils import daily_cron


def get_cron_jobs():
    return [
        daily_cron(
            coroutine=cleanup_expired_patient_exports,
            name="cleanup-expired-patient-exports",
            hour=2,
            minute=30,
            timeout_s=1800,
        )
    ]
