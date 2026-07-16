"""ARQ task entry points for the weightloss agentic loop."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import select

from lib.workers.tasks.base import task_with_logging

# Backoff for the holistic analysis retry loop. There is intentionally no
# fallback path: the analysis stays blocked until the LLM succeeds, so we keep
# retrying through the day (last delay repeats).
HOLISTIC_RETRY_DELAYS_MINUTES = [5, 15, 30]
HOLISTIC_MAX_ATTEMPTS = 20


@task_with_logging
async def run_agentic_cycle(ctx: Dict[str, Any], user_id: str) -> None:
    from lib.dependencies.service_dependencies import (
        get_agentic_orchestrator_service,
    )
    from lib.workers.arq.redis import enqueue_job

    orchestrator = get_agentic_orchestrator_service()
    await orchestrator.run_weekly_cycle(UUID(user_id))

    # Kick off the holistic analysis of the day that just completed; the
    # morning check-in stays blocked until this lands in Mongo.
    await enqueue_job(
        "run_daily_holistic_analysis",
        user_id,
        _job_id=f"holistic-daily-{user_id}-{datetime.utcnow().date().isoformat()}",
    )


@task_with_logging
async def run_daily_holistic_analysis(
    ctx: Dict[str, Any],
    user_id: str,
    date_str: Optional[str] = None,
    attempt: int = 1,
) -> None:
    """Generate the DailyCoachAnalysis for one completed patient-local day.

    On LLM failure the job re-enqueues itself with backoff — no message is
    delivered until an analysis exists (no rule-based fallback by design).
    """

    from lib.dependencies.service_dependencies import (
        get_holistic_summary_service,
    )
    from lib.workers.arq.redis import enqueue_job

    service = get_holistic_summary_service()
    patient_id = UUID(user_id)

    if date_str is None:
        timezone_name = (
            await service.holistic_data_service.get_patient_timezone(patient_id)
        )
        local_today = datetime.now(ZoneInfo(timezone_name)).date()
        target_date = local_today - timedelta(days=1)
        date_str = target_date.isoformat()
    else:
        target_date = date.fromisoformat(date_str)

    try:
        await service.generate_daily_coach_analysis(patient_id, target_date)
    except Exception as exc:
        if attempt >= HOLISTIC_MAX_ATTEMPTS:
            logger.error(
                f"❌ Holistic daily analysis exhausted retries "
                f"user={user_id} date={date_str} attempts={attempt}: {exc}"
            )
            return
        delay_index = min(attempt, len(HOLISTIC_RETRY_DELAYS_MINUTES)) - 1
        delay = timedelta(minutes=HOLISTIC_RETRY_DELAYS_MINUTES[delay_index])
        logger.warning(
            f"⚠️ Holistic daily analysis failed user={user_id} date={date_str} "
            f"attempt={attempt}; retrying in {delay} — {exc}"
        )
        await enqueue_job(
            "run_daily_holistic_analysis",
            user_id,
            date_str,
            attempt + 1,
            _defer_by=delay,
            _job_id=f"holistic-daily-{user_id}-{date_str}-a{attempt + 1}",
        )
        return

    # Weekly big-picture refresh piggybacks here; it is a no-op while the
    # stored summary is fresh. Its failure must not re-run the daily analysis.
    try:
        await service.refresh_summary_for_patient(patient_id)
    except Exception as exc:
        logger.warning(
            f"⚠️ Whole-person summary refresh failed user={user_id}: {exc}; "
            "re-queueing"
        )
        await enqueue_job(
            "run_whole_person_summary_for_patient",
            user_id,
            _defer_by=timedelta(minutes=15),
            _job_id=f"holistic-summary-{user_id}-{date_str}",
        )


@task_with_logging
async def sweep_agentic_checkins(ctx: Dict[str, Any]) -> None:
    """Every 15 min, run due check-ins for all active enrollments.

    ``run_scheduled_for_user`` is otherwise only triggered when the patient
    opens the chat; this sweep makes the morning/evening coach messages land
    at their checkpoint times without user activity.
    """

    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.dependencies.service_dependencies import get_agentic_chat_service
    from lib.models.weight_loss_agent import WeightLossAgentEnrollment

    store = container.resolve(PostgresStore)
    async with store.get_session() as session:
        result = await session.execute(
            select(WeightLossAgentEnrollment.patient_id).where(
                WeightLossAgentEnrollment.is_active.is_(True)
            )
        )
        patient_ids: List[UUID] = list(result.scalars().all())

    chat_service = get_agentic_chat_service()
    delivered = 0
    for patient_id in patient_ids:
        try:
            await chat_service.run_scheduled_for_user(patient_id)
            delivered += 1
        except Exception as exc:
            logger.error(
                f"⚠️ Check-in sweep failed for patient={patient_id}: {exc}"
            )

    logger.info(
        f"✅ Agentic check-in sweep done: {delivered}/{len(patient_ids)} patients"
    )


@task_with_logging
async def run_whole_person_summary(
    ctx: Dict[str, Any], enrollment_id: str, force: bool = False
) -> None:
    """Regenerate the whole-person summary for an enrollment (e.g. new InBody)."""

    from lib.dependencies.service_dependencies import (
        get_holistic_summary_service,
    )

    service = get_holistic_summary_service()
    await service.generate_whole_person_summary(UUID(enrollment_id), force=force)


@task_with_logging
async def run_whole_person_summary_for_patient(
    ctx: Dict[str, Any], user_id: str, force: bool = False
) -> None:
    """Retry hook for the weekly summary refresh, keyed by patient."""

    from lib.dependencies.service_dependencies import (
        get_holistic_summary_service,
    )

    service = get_holistic_summary_service()
    await service.refresh_summary_for_patient(UUID(user_id), force=force)


@task_with_logging
async def schedule_daily_agentic_cycles(ctx: Dict[str, Any]) -> None:
    """
    Enumerate all active weightloss enrollments and queue the async agentic
    loop for each user. Runs from ARQ cron at midnight IST.
    """
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.weight_loss_agent import WeightLossAgentEnrollment
    from lib.workers.arq.redis import enqueue_job

    store = container.resolve(PostgresStore)
    async with store.get_session() as session:
        result = await session.execute(
            select(WeightLossAgentEnrollment.patient_id).where(
                WeightLossAgentEnrollment.is_active.is_(True)
            )
        )
        patient_ids: List[UUID] = list(result.scalars().all())

    for patient_id in patient_ids:
        await enqueue_job("run_agentic_cycle", str(patient_id))

    logger.info(
        f"✅ Scheduled agentic cycles for {len(patient_ids)} active enrollments"
    )
