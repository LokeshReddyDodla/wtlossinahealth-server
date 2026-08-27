from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from dateutil.relativedelta import relativedelta
from sqlalchemy import select, update

from lib.workers.tasks.base import TaskResult, task_with_logging

logger = logging.getLogger(__name__)

_MAX_PREGNANCY_WEEKS = 42


@task_with_logging
async def clear_stale_pregnancies(ctx: dict[str, Any]) -> TaskResult:
    """Clear is_pregnant on both tables when pregnancy_weeks >= 42."""
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.patient_reproductive_health import PatientReproductiveHealth
    from lib.models.patient_diabetic_history import PatientDiabeticHistory

    store = container.resolve(PostgresStore)
    cleared = 0

    async with store.get_session() as session:
        for model in (PatientReproductiveHealth, PatientDiabeticHistory):
            result = await session.execute(
                update(model)
                .where(
                    model.is_pregnant.is_(True),
                    model.pregnancy_weeks >= _MAX_PREGNANCY_WEEKS,
                )
                .values(is_pregnant=None, pregnancy_weeks=None)
            )
            cleared += result.rowcount

        await session.commit()

    logger.info("clear_stale_pregnancies: cleared %d rows", cleared)
    return TaskResult(success=True, data={"cleared": cleared})


@task_with_logging
async def sync_diabetes_duration(ctx: dict[str, Any]) -> TaskResult:
    """Recompute years_with_diabetes from diagnosed_at where available."""
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.patient_diabetic_history import PatientDiabeticHistory

    store = container.resolve(PostgresStore)
    today = date.today()
    updated = 0

    async with store.get_session() as session:
        rows = (
            await session.scalars(
                select(PatientDiabeticHistory).where(
                    PatientDiabeticHistory.diagnosed_at.isnot(None)
                )
            )
        ).all()

        for row in rows:
            years = relativedelta(today, row.diagnosed_at).years
            fractional = years + relativedelta(today, row.diagnosed_at).months / 12.0
            rounded = round(fractional, 1)
            if row.years_with_diabetes != rounded:
                row.years_with_diabetes = rounded
                updated += 1

        await session.commit()

    logger.info("sync_diabetes_duration: updated %d rows", updated)
    return TaskResult(success=True, data={"updated": updated})


@task_with_logging
async def expire_stale_care_intents(ctx: dict[str, Any]) -> TaskResult:
    """Batch-expire active CareIntents past their review_date."""
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.care_intent import CareIntent

    store = container.resolve(PostgresStore)
    today = date.today()

    async with store.get_session() as session:
        result = await session.execute(
            update(CareIntent)
            .where(
                CareIntent.status == "active",
                CareIntent.review_date < today,
            )
            .values(status="expired")
        )
        expired = result.rowcount
        await session.commit()

    logger.info("expire_stale_care_intents: expired %d intents", expired)
    return TaskResult(success=True, data={"expired": expired})


_STALE_SYNC_DAYS = 30


@task_with_logging
async def mark_stale_connected_apps(ctx: dict[str, Any]) -> TaskResult:
    """Mark sync_status='stale' on connected apps with no sync in 30 days."""
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.patient_connected_app import PatientLibreView, PatientSinocare

    store = container.resolve(PostgresStore)
    cutoff = datetime.utcnow() - timedelta(days=_STALE_SYNC_DAYS)
    total = 0

    async with store.get_session() as session:
        for model in (PatientLibreView, PatientSinocare):
            result = await session.execute(
                update(model)
                .where(
                    model.sync_status == "active",
                    model.last_sync_timestamp < cutoff,
                )
                .values(sync_status="stale")
            )
            total += result.rowcount

        await session.commit()

    logger.info("mark_stale_connected_apps: marked %d stale", total)
    return TaskResult(success=True, data={"marked_stale": total})
