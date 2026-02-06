"""Shared cron job helpers for ARQ tasks."""

from typing import Callable

from arq.cron import CronJob


def weekly_cron(
    *,
    coroutine: Callable,
    name: str,
    weekday: int,
    hour: int,
    minute: int = 0,
    timeout_s: float = 600,
    run_at_startup: bool = False,
) -> CronJob:
    """
    Helper to create a weekly cron job.

    Args:
        coroutine: Async function to run
        name: Job name and ID
        weekday: Day of week (0=Sunday, 1=Monday, ..., 6=Saturday)
        hour: Hour of day (0-23)
        minute: Minute of hour (0-59), default 0
        timeout_s: Job timeout in seconds, default 600
        run_at_startup: Whether to run on worker startup, default False

    Returns:
        Configured CronJob instance
    """
    return CronJob(
        coroutine=coroutine,
        name=name,
        month=None,
        day=None,
        weekday={weekday},
        hour={hour},
        minute={minute},
        second={0},
        microsecond=0,
        unique=True,
        job_id=name,
        timeout_s=timeout_s,
        keep_result_s=0,
        keep_result_forever=False,
        max_tries=1,
        run_at_startup=run_at_startup,
    )


def daily_cron(
    *,
    coroutine: Callable,
    name: str,
    hour: int,
    minute: int = 0,
    timeout_s: float = 600,
    run_at_startup: bool = False,
) -> CronJob:
    """
    Helper to create a daily cron job.

    Args:
        coroutine: Async function to run
        name: Job name and ID
        hour: Hour of day (0-23)
        minute: Minute of hour (0-59), default 0
        timeout_s: Job timeout in seconds, default 600
        run_at_startup: Whether to run on worker startup, default False

    Returns:
        Configured CronJob instance
    """
    return CronJob(
        coroutine=coroutine,
        name=name,
        month=None,
        day=None,
        weekday=None,
        hour={hour},
        minute={minute},
        second={0},
        microsecond=0,
        unique=True,
        job_id=name,
        timeout_s=timeout_s,
        keep_result_s=0,
        keep_result_forever=False,
        max_tries=1,
        run_at_startup=run_at_startup,
    )


def monthly_cron(
    *,
    coroutine: Callable,
    name: str,
    day: int,
    hour: int,
    minute: int = 0,
    timeout_s: float = 600,
    run_at_startup: bool = False,
) -> CronJob:
    """
    Helper to create a monthly cron job.

    Args:
        coroutine: Async function to run
        name: Job name and ID
        day: Day of month (1-31)
        hour: Hour of day (0-23)
        minute: Minute of hour (0-59), default 0
        timeout_s: Job timeout in seconds, default 600
        run_at_startup: Whether to run on worker startup, default False

    Returns:
        Configured CronJob instance
    """
    return CronJob(
        coroutine=coroutine,
        name=name,
        month=None,
        day={day},
        weekday=None,
        hour={hour},
        minute={minute},
        second={0},
        microsecond=0,
        unique=True,
        job_id=name,
        timeout_s=timeout_s,
        keep_result_s=0,
        keep_result_forever=False,
        max_tries=1,
        run_at_startup=run_at_startup,
    )
