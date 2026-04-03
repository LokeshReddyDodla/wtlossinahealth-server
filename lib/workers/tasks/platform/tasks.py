"""Platform-level background tasks — plan lifecycle, data cleanup, etc."""

from datetime import date
from typing import Any, Dict

from loguru import logger
from sqlalchemy import select

from lib.workers.tasks.base import task_with_logging


@task_with_logging
async def archive_expired_plans(ctx: Dict[str, Any]) -> None:
    """Archive diet and fitness plans whose end_date has passed.
    Runs daily at 00:30 UTC.
    """
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.patient_diet_plan import PatientDietPlan
    from lib.models.patient_fitness_plan import PatientFitnessPlan

    store = container.resolve(PostgresStore)
    today = date.today()
    archived = 0

    async with store.get_session() as session:
        # Diet plans
        result = await session.execute(
            select(PatientDietPlan).where(
                PatientDietPlan.status == "ACTIVE",
                PatientDietPlan.end_date.is_not(None),
                PatientDietPlan.end_date < today,
            )
        )
        for plan in result.scalars().all():
            plan.status = "ARCHIVED"
            archived += 1

        # Fitness plans
        result = await session.execute(
            select(PatientFitnessPlan).where(
                PatientFitnessPlan.status == "ACTIVE",
                PatientFitnessPlan.end_date.is_not(None),
                PatientFitnessPlan.end_date < today,
            )
        )
        for plan in result.scalars().all():
            plan.status = "ARCHIVED"
            archived += 1

        if archived:
            await session.commit()

    logger.info(f"Plan archival: {archived} expired plans archived")
