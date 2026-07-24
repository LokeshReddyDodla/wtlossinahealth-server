"""ARQ tasks for the InBody daily summary.

End of day, one job per InBody patient asks the health agent to summarize the
patient's day. The agent already holds the patient's full context, so there is
no data-gathering or LLM prompting of our own — we send one question and store
the reply in Mongo (``inbody_day_summaries``), which the API reads.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List
from uuid import UUID
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import select

from lib.workers.tasks.base import task_with_logging

# Summaries are keyed and dated in the platform's default timezone.
SUMMARY_TIMEZONE = "Asia/Kolkata"

DAY_SUMMARY_QUESTION = (
    "Give me a short summary of how I did today ({day}) — my meals, activity, "
    "glucose, sleep and medications — and how it fits my body-composition "
    "goals from my InBody scans. Keep it warm, specific and under 150 words, "
    "and end with one thing to focus on tomorrow. Only use data you actually "
    "have; if a part of the day has no data, say so instead of guessing."
)


@task_with_logging
async def schedule_inbody_day_summaries(ctx: Dict[str, Any]) -> None:
    """Fan out one summary job per patient with a usable InBody report.

    Runs from ARQ cron at end of day.
    """
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.patient_inbody_report import PatientInbodyReport
    from lib.workers.arq.redis import enqueue_job

    store = container.resolve(PostgresStore)
    async with store.get_session() as session:
        result = await session.execute(
            select(PatientInbodyReport.patient_id)
            .where(
                PatientInbodyReport.status.in_(["extracted", "needs_review"])
            )
            .distinct()
        )
        patient_ids: List[UUID] = list(result.scalars().all())

    for patient_id in patient_ids:
        await enqueue_job(
            "generate_inbody_day_summary",
            str(patient_id),
            _job_id=f"inbody-day-summary-{patient_id}-{date.today().isoformat()}",
        )

    logger.info(
        f"✅ Scheduled InBody day summaries for {len(patient_ids)} patients"
    )


@task_with_logging
async def generate_inbody_day_summary(
    ctx: Dict[str, Any], patient_id: str
) -> None:
    from lib.ai_foundation.agents.state import (
        AgentContext,
        AgentInput,
        RequestPriority,
    )
    from lib.dependencies.service_dependencies import (
        get_health_query_agent,
        get_inbody_day_summary_service,
    )

    summary_date = datetime.now(ZoneInfo(SUMMARY_TIMEZONE)).date()

    agent = get_health_query_agent()
    output = await agent.run(
        AgentInput(
            message=DAY_SUMMARY_QUESTION.format(day=summary_date.isoformat()),
            context=AgentContext(
                patient_id=patient_id,
                user_id=patient_id,
                user_role="patient",
                # Isolated thread so day summaries never touch the patient's
                # real chat history.
                thread_id=f"inbody-day-summary-{patient_id}",
                patient_ids=[patient_id],
                priority=RequestPriority.LOW,
            ),
        )
    )

    summary_text = (output.message or "").strip()
    if not summary_text:
        raise ValueError(
            f"Health agent returned an empty day summary patient={patient_id}"
        )

    summary_service = get_inbody_day_summary_service()
    await summary_service.save(UUID(patient_id), summary_date, summary_text)

    logger.info(
        f"✅ InBody day summary stored patient={patient_id} date={summary_date}"
    )
