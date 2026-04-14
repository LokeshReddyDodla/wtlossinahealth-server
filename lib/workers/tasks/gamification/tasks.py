"""ARQ task entry points for gamification background jobs."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from lib.services.gamification.time_utils import local_today, matches_local_hour
from lib.workers.tasks.base import task_with_logging


@task_with_logging
async def process_streaks_for_all(ctx: Dict[str, Any]) -> None:
    """Nightly streak processor — evaluate all active patients.
    Runs at 2:00 AM (configured per patient timezone in future).
    """
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.patient import Patient
    from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
    from lib.services.gamification.streak_service import StreakService

    store = container.resolve(PostgresStore)
    streak_service = container.resolve(StreakService)
    resolver = container.resolve(PatientNameResolver)

    async with store.get_session() as session:
        result = await session.execute(
            select(Patient.patient_id)
        )
        patient_ids: List[UUID] = list(result.scalars().all())

    tz_map = await resolver.resolve_timezones([str(pid) for pid in patient_ids])

    processed = 0
    for pid in patient_ids:
        try:
            tz_name = tz_map.get(str(pid))
            if not matches_local_hour(tz_name, 2):
                continue
            target_date = local_today(tz_name) - timedelta(days=1)
            await streak_service.process_streak(pid, target_date)
            await streak_service.process_buddy_streaks(pid, target_date)
            processed += 1
        except Exception:
            logger.opt(exception=True).warning(
                f"Streak processing failed for {pid}"
            )

    logger.info(f"Processed streaks for {processed}/{len(patient_ids)} patients")


@task_with_logging
async def generate_daily_tasks_for_all(ctx: Dict[str, Any]) -> None:
    """Daily task generator — generate tasks from active plans.
    Runs at 5:00 AM.
    """
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.patient import Patient
    from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
    from lib.services.gamification.task_generator import TaskGeneratorService

    store = container.resolve(PostgresStore)
    task_gen = container.resolve(TaskGeneratorService)
    resolver = container.resolve(PatientNameResolver)

    # Monday = 0 in Python weekday()
    async with store.get_session() as session:
        result = await session.execute(
            select(Patient.patient_id)
        )
        patient_ids: List[UUID] = list(result.scalars().all())

    tz_map = await resolver.resolve_timezones([str(pid) for pid in patient_ids])

    generated = 0
    for pid in patient_ids:
        try:
            tz_name = tz_map.get(str(pid))
            if not matches_local_hour(tz_name, 5):
                continue
            today = local_today(tz_name)
            is_monday = today.weekday() == 0
            week_start = today - timedelta(days=today.weekday())

            # Expire yesterday's pending tasks
            await task_gen.expire_old_tasks(pid, today)

            # Generate today's tasks
            await task_gen.generate_daily_tasks(pid, today)

            # Generate weekly quest on Mondays
            if is_monday:
                await task_gen.generate_weekly_quest(pid, week_start)

            generated += 1
        except Exception:
            logger.opt(exception=True).warning(
                f"Task generation failed for {pid}"
            )

    logger.info(f"Generated tasks for {generated}/{len(patient_ids)} patients")


@task_with_logging
async def evaluate_eod_macros(ctx: Dict[str, Any]) -> None:
    """End-of-day macro evaluator — check calorie/protein targets.
    Runs at 11:00 PM.
    """
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
    from lib.models.gamification import DailyTask
    from lib.services.gamification.event_handler import GamificationEventHandler

    from lib.services.reports.meal.processor import MealStatsProcessor

    store = container.resolve(PostgresStore)
    event_handler = container.resolve(GamificationEventHandler)
    meal_processor = container.resolve(MealStatsProcessor)
    resolver = container.resolve(PatientNameResolver)

    async with store.get_session() as session:
        result = await session.execute(
            select(DailyTask.patient_id)
            .where(
                DailyTask.task_type.in_([
                    "HIT_CALORIE_TARGET",
                    "HIT_PROTEIN_TARGET",
                ]),
                DailyTask.status == "pending",
            )
            .distinct()
        )
        patient_ids = list(result.scalars().all())

    tz_map = await resolver.resolve_timezones([str(pid) for pid in patient_ids])

    logger.info(f"EOD macro eval for {len(patient_ids)} patients with pending macro tasks")

    evaluated = 0
    for pid in patient_ids:
        try:
            tz_name = tz_map.get(str(pid))
            if not matches_local_hour(tz_name, 23):
                continue
            today = local_today(tz_name)
            daily_stats = await meal_processor.get_meal_report_by_date(
                str(pid), today
            )
            if daily_stats:
                await event_handler.on_macro_data_available(
                    pid,
                    total_calories=getattr(daily_stats, "calories", None),
                    total_protein=getattr(daily_stats, "proteins", None),
                )
                evaluated += 1
        except Exception:
            logger.opt(exception=True).warning(
                f"EOD macro eval failed for {pid}"
            )

    logger.info(f"EOD macro eval completed: {evaluated}/{len(patient_ids)}")


@task_with_logging
async def refresh_leaderboards(ctx: Dict[str, Any]) -> None:
    """Leaderboard refresh — recompute rankings.
    Runs every 15 minutes.
    """
    from lib.core.container import container
    from lib.services.gamification.leaderboard_service import LeaderboardService

    lb_service = container.resolve(LeaderboardService)

    try:
        await lb_service.refresh_all_boards()
        logger.info("Leaderboards refreshed")
    except Exception:
        logger.opt(exception=True).warning("Leaderboard refresh failed")


@task_with_logging
async def process_challenge_lifecycle(ctx: Dict[str, Any]) -> None:
    """Challenge lifecycle — start/end challenges, compute rankings.
    Runs hourly.
    """
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.gamification import Challenge
    from lib.services.gamification.challenge_service import ChallengeService

    store = container.resolve(PostgresStore)
    challenge_service = container.resolve(ChallengeService)
    ended_ids = await challenge_service.get_finalizable_challenge_ids()

    for cid in ended_ids:
        try:
            await challenge_service.finalize_challenge(cid)
            logger.info(f"Finalized challenge {cid}")
        except Exception:
            logger.opt(exception=True).warning(
                f"Challenge finalization failed for {cid}"
            )


@task_with_logging
async def send_streak_reminders(ctx: Dict[str, Any]) -> None:
    """Streak reminder — nudge patients at risk of losing their streak.
    Runs hourly; worker filters by patient-local 8:00 PM.
    """
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.gamification import DailyTask, PlayerProfile
    from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
    from lib.services.gamification.notifications import send_gamification_notification
    from lib.services.gamification.streak_service import ACTIVITY_TASK_TYPES, ACTIVITY_THRESHOLD
    from lib.schemas.gamification import TaskStatus
    from lib.services.notification_budget import can_send, record_sent

    store = container.resolve(PostgresStore)
    resolver = container.resolve(PatientNameResolver)

    async with store.get_session() as session:
        result = await session.execute(
            select(PlayerProfile.patient_id, PlayerProfile.current_streak).where(
                PlayerProfile.current_streak > 0
            )
        )
        rows = result.all()

    if not rows:
        return

    streak_map = {r.patient_id: r.current_streak for r in rows}
    patient_ids = list(streak_map.keys())
    tz_map = await resolver.resolve_timezones([str(pid) for pid in patient_ids])

    sent = 0
    for pid in patient_ids:
        try:
            tz_name = tz_map.get(str(pid))
            if not matches_local_hour(tz_name, 20):
                continue

            today = local_today(tz_name)

            async with store.get_session() as session:
                task_result = await session.execute(
                    select(DailyTask.task_type)
                    .where(
                        DailyTask.patient_id == pid,
                        DailyTask.task_date == today,
                        DailyTask.status == TaskStatus.COMPLETED.value,
                        DailyTask.task_type.in_(ACTIVITY_TASK_TYPES),
                    )
                    .distinct()
                )
                completed_types = len(task_result.scalars().all())

            if completed_types >= ACTIVITY_THRESHOLD:
                continue

            streak = streak_map[pid]
            if not can_send(str(pid), "streak_reminder"):
                continue
            await send_gamification_notification(
                str(pid),
                title="Don't lose your streak!",
                body=f"You're on a {streak}-day streak. Complete a task to keep it going!",
                data={"event_type": "streak_reminder", "current_streak": streak},
            )
            record_sent(str(pid))
            sent += 1
        except Exception:
            logger.opt(exception=True).warning(f"Streak reminder failed for {pid}")

    logger.info(f"Sent streak reminders to {sent}/{len(patient_ids)} patients")


@task_with_logging
async def cleanup_feed_and_leaderboards(ctx: Dict[str, Any]) -> None:
    """Cleanup expired feed events and old leaderboard entries.
    Runs daily.
    """
    from lib.core.container import container
    from lib.services.gamification.feed_service import FeedService
    from lib.services.gamification.leaderboard_service import LeaderboardService

    feed_service = container.resolve(FeedService)
    lb_service = container.resolve(LeaderboardService)

    feed_count = await feed_service.cleanup_expired()
    lb_count = await lb_service.cleanup_old_entries(days=90)

    logger.info(
        f"Cleanup: {feed_count} feed events, {lb_count} leaderboard entries removed"
    )


# ── Medication cron tasks ────────────────────────────────────────────────


async def _send_medication_notification(
    patient_id: str,
    *,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> None:
    """FCM notification on the 'reminders' channel — separate from gamification."""
    try:
        from lib.services.fcm_service import FCMService
        from lib.services.notification_budget import record_sent

        await FCMService().send_fcm_notification_to_user_devices(
            user_id=patient_id,
            title=title,
            body=body,
            channel_key="reminders",
            group_key="reminder_group",
            data={"type": "medication", **(data or {})},
        )
        record_sent(patient_id)
    except Exception as exc:
        logger.warning("Failed medication notification for %s: %s", patient_id, exc)


_MEDICATION_REMINDER_SLOTS = {
    10: "TAKE_MEDICATION_MORNING",
    15: "TAKE_MEDICATION_AFTERNOON",
    21: "TAKE_MEDICATION_EVENING",
    23: "TAKE_MEDICATION_NIGHT",
}


@task_with_logging
async def send_medication_reminders(ctx: Dict[str, Any]) -> None:
    """Medication reminder — nudge patients to take their meds.
    Runs hourly; filters by patient-local time for each slot.
    """
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.gamification import DailyTask
    from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
    from lib.schemas.gamification import TaskStatus

    store = container.resolve(PostgresStore)
    resolver = container.resolve(PatientNameResolver)

    from lib.models.patient_medication import PatientMedication

    async with store.get_session() as session:
        result = await session.execute(
            select(PatientMedication.patient_id)
            .where(PatientMedication.status == "active")
            .distinct()
        )
        patient_ids = [r[0] for r in result.all()]

    if not patient_ids:
        return

    tz_map = await resolver.resolve_timezones([str(pid) for pid in patient_ids])

    sent = 0
    for pid in patient_ids:
        try:
            tz_name = tz_map.get(str(pid))

            for hour, task_type in _MEDICATION_REMINDER_SLOTS.items():
                if not matches_local_hour(tz_name, hour):
                    continue

                today = local_today(tz_name)
                async with store.get_session() as session:
                    task_result = await session.execute(
                        select(DailyTask).where(
                            DailyTask.patient_id == pid,
                            DailyTask.task_date == today,
                            DailyTask.task_type == task_type,
                            DailyTask.status == TaskStatus.PENDING.value,
                        )
                    )
                    pending_task = task_result.scalars().first()

                if pending_task:
                    slot_name = task_type.replace("TAKE_MEDICATION_", "").lower()
                    body = (
                        f"Time to take: {pending_task.description}"
                        if pending_task.description
                        else f"Time to take your {slot_name} medications"
                    )
                    await _send_medication_notification(
                        str(pid),
                        title="Medication reminder",
                        body=body,
                        data={"event_type": "medication_reminder", "slot": slot_name},
                    )
                    sent += 1
        except Exception:
            logger.opt(exception=True).warning(f"Medication reminder failed for {pid}")

    logger.info(f"Sent medication reminders to {sent} patients")


@task_with_logging
async def send_follow_up_reminders(ctx: Dict[str, Any]) -> None:
    """Follow-up appointment reminder — notify patients at 8 AM local.
    Runs hourly; filters by patient-local 8:00 AM.
    """
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.gamification import DailyTask
    from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
    from lib.schemas.gamification import TaskStatus, TaskType

    store = container.resolve(PostgresStore)
    resolver = container.resolve(PatientNameResolver)

    async with store.get_session() as session:
        result = await session.execute(
            select(DailyTask.patient_id)
            .where(
                DailyTask.task_type == TaskType.FOLLOW_UP_APPOINTMENT.value,
                DailyTask.status == TaskStatus.PENDING.value,
            )
            .distinct()
        )
        patient_ids = [r[0] for r in result.all()]

    if not patient_ids:
        return

    tz_map = await resolver.resolve_timezones([str(pid) for pid in patient_ids])

    sent = 0
    for pid in patient_ids:
        try:
            tz_name = tz_map.get(str(pid))
            if not matches_local_hour(tz_name, 8):
                continue

            today = local_today(tz_name)
            async with store.get_session() as session:
                task_result = await session.execute(
                    select(DailyTask).where(
                        DailyTask.patient_id == pid,
                        DailyTask.task_date == today,
                        DailyTask.task_type == TaskType.FOLLOW_UP_APPOINTMENT.value,
                        DailyTask.status == TaskStatus.PENDING.value,
                    )
                )
                pending_task = task_result.scalars().first()

            if pending_task:
                await _send_medication_notification(
                    str(pid),
                    title="Follow-up appointment today",
                    body=pending_task.description or "You have a scheduled follow-up appointment today",
                    data={"event_type": "follow_up_reminder"},
                )
                sent += 1
        except Exception:
            logger.opt(exception=True).warning(f"Follow-up reminder failed for {pid}")

    logger.info(f"Sent follow-up reminders to {sent} patients")


@task_with_logging
async def complete_expired_medications(ctx: Dict[str, Any]) -> None:
    """Mark medications past their end_date as completed. Runs daily."""
    from lib.core.container import container
    from lib.services.medication_service import MedicationService

    service = container.resolve(MedicationService)
    count = await service.complete_expired_medications()
    logger.info(f"Completed {count} expired medications")


@task_with_logging
async def send_refill_reminders(ctx: Dict[str, Any]) -> None:
    """Remind patients whose medication course ends in 3 days.
    Runs hourly; filters by patient-local 9:00 AM.
    """
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.patient_medication import PatientMedication
    from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
    from lib.services.gamification.notifications import send_gamification_notification

    store = container.resolve(PostgresStore)
    resolver = container.resolve(PatientNameResolver)

    from datetime import timedelta as td

    # Get all patients with active medications that have end dates
    async with store.get_session() as session:
        result = await session.execute(
            select(PatientMedication).where(
                PatientMedication.status == "active",
                PatientMedication.end_date.isnot(None),
            )
        )
        all_medications = result.scalars().all()

    if not all_medications:
        return

    patient_ids = list({str(m.patient_id) for m in all_medications})
    tz_map = await resolver.resolve_timezones(patient_ids)

    sent = 0
    for med in all_medications:
        try:
            pid = str(med.patient_id)
            tz_name = tz_map.get(pid)
            if not matches_local_hour(tz_name, 9):
                continue

            today = local_today(tz_name)
            name = f"{med.name} {med.strength}" if med.strength else med.name

            # Check 7-day and 3-day thresholds
            days_left = (med.end_date - today).days
            if days_left not in (7, 3):
                continue

            await _send_medication_notification(
                pid,
                title="Course ending soon",
                body=f"Your {name} course ends in {days_left} days. Contact your doctor if you need a refill.",
                data={"event_type": "refill_reminder", "medication_id": str(med.medication_id)},
            )
            sent += 1
        except Exception:
            logger.opt(exception=True).warning(f"Refill reminder failed for {med.patient_id}")

    logger.info(f"Sent refill reminders to {sent} patients")
