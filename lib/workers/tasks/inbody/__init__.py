"""InBody ARQ tasks."""

from lib.workers.tasks.inbody.tasks import run_inbody_insight

__all__ = ["run_inbody_insight", "get_tasks"]


def get_tasks():
    """Return InBody tasks for the ARQ worker."""
    return [run_inbody_insight]
