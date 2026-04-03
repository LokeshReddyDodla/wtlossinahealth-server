"""Cron job definitions for platform-level background tasks."""

from arq.cron import cron

from lib.workers.tasks.platform.tasks import archive_expired_plans

PLATFORM_CRON_JOBS = [
    # Archive expired plans — daily at 00:30 UTC
    cron(
        archive_expired_plans,
        hour=0,
        minute=30,
        timeout=300,
        unique=True,
    ),
]
