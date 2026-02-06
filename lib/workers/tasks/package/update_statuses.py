"""Package assignment status update tasks."""

from datetime import date, datetime
from typing import Any, Dict

from loguru import logger
from sqlalchemy import update
from sqlalchemy.future import select

from lib.dependencies.database import get_async_postgres_session
from lib.models.patient_package_assignment import (
    AssignmentStatus,
    PatientPackageAssignment,
)
from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def update_package_assignment_statuses(
    ctx: Dict[str, Any],
) -> TaskResult:
    """Update expired package assignments from ACTIVE to EXPIRED."""
    try:
        async with get_async_postgres_session() as session:
            today = date.today()

            stmt = select(PatientPackageAssignment).where(
                PatientPackageAssignment.status == AssignmentStatus.ACTIVE,
                PatientPackageAssignment.end_date < today,
            )

            result = await session.execute(stmt)
            expired_assignments = result.scalars().all()

            if not expired_assignments:
                logger.info("No expired assignments to update")
                return TaskResult(
                    success=True,
                    data={"updated_count": 0, "message": "no_expired_assignments"},
                )

            update_stmt = (
                update(PatientPackageAssignment)
                .where(
                    PatientPackageAssignment.status == AssignmentStatus.ACTIVE,
                    PatientPackageAssignment.end_date < today,
                )
                .values(
                    status=AssignmentStatus.EXPIRED,
                    updated_at=datetime.now().replace(tzinfo=None),
                )
            )

            await session.execute(update_stmt)
            await session.commit()

            logger.info(
                f"Updated {len(expired_assignments)} assignments to EXPIRED status"
            )

            return TaskResult(
                success=True,
                data={
                    "updated_count": len(expired_assignments),
                },
            )

    except Exception as e:
        logger.error(f"Failed to update package assignment statuses: {e}")
        return TaskResult(
            success=False,
            error=str(e),
        )


async def _enqueue_update_package_assignment_statuses() -> str | None:
    """Internal: Enqueue package assignment status update."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    job_id = f"package:update_statuses:{timestamp}"

    job = await enqueue_job(
        "update_package_assignment_statuses",
        _job_id=job_id,
        _queue_name=Queues.DEFAULT,
    )

    if job:
        logger.info("Enqueued package assignment status update")
    else:
        logger.debug(f"Duplicate package assignment status update skipped: {job_id}")

    return job.job_id if job else None
