"""Qdrant coverage reconciler tasks."""

from lib.workers.tasks.vector_coverage.sweep import vector_coverage_sweep

__all__ = ["vector_coverage_sweep", "get_tasks", "get_cron_jobs"]


def get_tasks():
    from arq.worker import func

    return [func(vector_coverage_sweep, name="vector_coverage_sweep", keep_result=0)]


def get_cron_jobs():
    from lib.workers.tasks.utils.cron_helpers import weekly_cron

    # The one deliberate cron in the derived-data era: Qdrant is fed by an
    # external paid API that can fail silently, so it gets a weekly
    # correctness floor. Diff-first — a healthy week costs reads, no
    # embeddings.
    return [
        weekly_cron(
            coroutine=vector_coverage_sweep,
            name="vector-coverage-sweep",
            weekday=0,
            hour=3,
            timeout_s=600,
        )
    ]
