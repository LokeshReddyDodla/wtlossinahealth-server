"""ARQ Task Manager."""

from typing import List, Optional, Tuple

from lib.workers.arq.redis import enqueue_job, get_arq_pool


class ArqTaskManager:
    async def enqueue_task(
        self,
        task_name: str,
        *args,
        task_id: Optional[str] = None,
        queue_name: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        job = await enqueue_job(
            task_name, *args, _job_id=task_id, _queue_name=queue_name, **kwargs
        )
        return job.job_id if job else None
    
    async def enqueue_cgm_report_generation(
        self, patient_id: str, periods: List[Tuple]
    ) -> Optional[str]:
        from lib.workers.tasks.cgm.report_generation import enqueue_cgm_reports
        return await enqueue_cgm_reports(patient_id, periods)
    
    async def health_check(self) -> bool:
        try:
            pool = await get_arq_pool()
            await pool.ping()
            return True
        except Exception:
            return False


_manager: Optional[ArqTaskManager] = None


def get_arq_task_manager() -> ArqTaskManager:
    global _manager
    if _manager is None:
        _manager = ArqTaskManager()
    return _manager
