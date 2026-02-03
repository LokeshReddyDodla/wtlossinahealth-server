"""Task registry - aggregates all tasks for ARQ worker."""

from typing import Callable, List

from loguru import logger


def get_all_tasks() -> List[Callable]:
    tasks = []
    
    from lib.workers.tasks.cgm import get_tasks as get_cgm_tasks
    from lib.workers.tasks.fcm import get_tasks as get_fcm_tasks
    
    tasks.extend(get_cgm_tasks())
    tasks.extend(get_fcm_tasks())
    
    logger.info(f"Registered {len(tasks)} ARQ tasks")
    return tasks


__all__ = ["get_all_tasks"]
