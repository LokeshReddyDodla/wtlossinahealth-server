"""ARQ Task Manager."""

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

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

    async def enqueue_daily_meal_report(
        self, patient_id: str, report_date: date | str
    ) -> Optional[str]:
        """Enqueue daily meal report generation (async)."""
        from lib.workers.tasks.meal.enqueue import enqueue_daily_meal_report_async
        return await enqueue_daily_meal_report_async(patient_id, report_date)

    def enqueue_daily_meal_report_sync(
        self, patient_id: str, report_date: date | str
    ) -> Optional[str]:
        """Enqueue daily meal report generation (sync)."""
        import asyncio
        import nest_asyncio

        nest_asyncio.apply()
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            self.enqueue_daily_meal_report(patient_id, report_date)
        )

    async def enqueue_meal_vector(
        self, patient_id: str, meal_id: str, meal_data: Dict[str, Any]
    ) -> Optional[str]:
        """Enqueue meal vector generation (async)."""
        from lib.workers.tasks.meal.enqueue import enqueue_meal_vector_async
        return await enqueue_meal_vector_async(patient_id, meal_id, meal_data)

    def enqueue_meal_vector_sync(
        self, patient_id: str, meal_id: str, meal_data: Dict[str, Any]
    ) -> Optional[str]:
        """Enqueue meal vector generation (sync)."""
        import asyncio
        import nest_asyncio

        nest_asyncio.apply()
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            self.enqueue_meal_vector(patient_id, meal_id, meal_data)
        )

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
