"""Patient summary tasks for ARQ worker."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict

from loguru import logger

from lib.services.patient_summary.enum import RegeneratedBy
from lib.utils.timezone import get_ist_now
from lib.workers.tasks.base import task_with_logging


@task_with_logging
async def generate_yesterdays_daily_summary(
    ctx: Dict[str, Any], patient_id: str
) -> None:
    try:
        from lib.dependencies.service_dependencies import (
            get_patient_summary_service,
        )

        service = get_patient_summary_service()
        target_date = (get_ist_now() - timedelta(days=1)).date()
        logger.info(f"==> target_date: {target_date}")

        await service.generate_daily_summary(
            patient_id=patient_id,
            target_date=target_date,
            regenerated_by=RegeneratedBy.SYSTEM,
        )

        logger.info(
            f"✅ Generated yesterday's daily summary for {patient_id} ({target_date})"
        )
    except Exception as e:
        logger.error(
            f"❌ Failed to generate yesterday's summary for {patient_id}: {e}"
        )
        raise


@task_with_logging
async def schedule_daily_patient_summaries(ctx: Dict[str, Any]) -> None:
    try:
        from lib.dependencies.service_dependencies import (
            get_active_patient_service,
        )
        from lib.workers.arq.redis import enqueue_job

        service = get_active_patient_service()
        patient_ids = await service.get_active_patients(days=3)

        for patient_id in patient_ids:
            await enqueue_job(
                "generate_yesterdays_daily_summary",
                patient_id,
            )

        logger.info(
            f"✅ Scheduled yesterday's summaries for {len(patient_ids)} patients"
        )
    except Exception as e:
        logger.error(f"❌ Failed to schedule daily summaries: {e}")
        raise


@task_with_logging
async def generate_daily_summary_for_patient(
    ctx: Dict[str, Any],
    patient_id: str,
    target_date_str: str,
    forced: bool = False,
) -> None:
    try:
        from lib.dependencies.service_dependencies import (
            get_patient_summary_service,
        )

        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        service = get_patient_summary_service()
        await service.generate_daily_summary(
            patient_id=patient_id,
            target_date=target_date,
            regenerated_by=RegeneratedBy.SYSTEM,
            forced=forced,
        )

        logger.info(
            f"✅ Generated daily summary for {patient_id} on {target_date}"
        )
    except Exception as e:
        logger.error(
            f"❌ Failed to generate daily summary for {patient_id} on {target_date_str}: {e}"
        )
        raise


@task_with_logging
async def generate_summaries_for_date(
    ctx: Dict[str, Any],
    date_str: str,
    forced: bool = False,
    days: int = 3,
) -> None:
    try:
        from lib.dependencies.service_dependencies import (
            get_active_patient_service,
        )
        from lib.workers.arq.redis import enqueue_job

        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        service = get_active_patient_service()
        patient_ids = await service.get_active_patients(days=days)

        for patient_id in patient_ids:
            await enqueue_job(
                "generate_daily_summary_for_patient",
                patient_id,
                target_date.strftime("%Y-%m-%d"),
                forced,
            )

        logger.info(
            f"✅ Scheduled summaries for {len(patient_ids)} patients on {target_date}"
        )
    except ValueError as e:
        logger.error(
            f"❌ Invalid date format '{date_str}'. Expected YYYY-MM-DD format: {e}"
        )
        raise
    except Exception as e:
        logger.error(f"❌ Failed to schedule summaries for date {date_str}: {e}")
        raise


@task_with_logging
async def regenerate_stale_summaries(ctx: Dict[str, Any]) -> None:
    try:
        from lib.dependencies.service_dependencies import (
            get_patient_summary_service,
        )

        service = get_patient_summary_service()
        stale_summaries = await service.get_stale_summaries()

        if not stale_summaries:
            logger.info("ℹ️ No stale summaries found")
            return

        regenerated_count = 0
        failed_count = 0

        for summary in stale_summaries:
            try:
                patient_id = summary.get("patient_id")
                date_str = summary.get("date")

                if not patient_id or not date_str:
                    logger.warning(
                        f"⚠️ Skipping summary with missing patient_id or date: {summary.get('_id')}"
                    )
                    failed_count += 1
                    continue

                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

                await service.generate_daily_summary(
                    patient_id=patient_id,
                    target_date=target_date,
                    regenerated_by=RegeneratedBy.SYSTEM,
                    forced=True,
                )

                regenerated_count += 1
                logger.info(
                    f"✅ Regenerated stale summary for {patient_id} on {target_date}"
                )
            except Exception as e:
                failed_count += 1
                logger.error(
                    f"❌ Failed to regenerate stale summary for {summary.get('patient_id')} "
                    f"on {summary.get('date')}: {e}"
                )

        logger.info(
            f"✅ Regenerated {regenerated_count} stale summaries "
            f"({failed_count} failed out of {len(stale_summaries)} total)"
        )
    except Exception as e:
        logger.error(f"❌ Failed to regenerate stale summaries: {e}")
        raise
