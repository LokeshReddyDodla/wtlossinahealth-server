"""Health query agent tasks."""

from lib.workers.tasks.health_query_agent.compaction import compact_health_query_thread

__all__ = ["compact_health_query_thread", "get_tasks", "get_cron_jobs"]


def get_tasks():
    return [compact_health_query_thread]


def get_cron_jobs():
    return []
