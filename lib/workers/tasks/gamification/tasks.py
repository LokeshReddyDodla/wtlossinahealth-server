"""ARQ task entry points for gamification background jobs."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from lib.workers.tasks.base import task_with_logging


@task_with_logging
async def process_streaks_for_all(ctx: Dict[str, Any]) -> None:
    """Nightly streak processor — evaluate all active patients.
    Runs at 2:00 AM (configured per patient timezone in future).
    """
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.gamification import PlayerProfile
    from lib.services.gamification.streak_service import StreakService

    store = container.resolve(PostgresStore)
    streak_service = container.resolve(StreakService)

    yesterday = date.today() - timedelta(days=1)

    async with store.get_session() as session:
        result = await session.execute(
            select(PlayerProfile.patient_id)
        )
        patient_ids: List[UUID] = list(result.scalars().all())

    processed = 0
    for pid in patient_ids:
        try:
            await streak_service.process_streak(pid, yesterday)
            await streak_service.process_buddy_streaks(pid, yesterday)
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
    from lib.models.gamification import PlayerProfile
    from lib.services.gamification.task_generator import TaskGeneratorService

    store = container.resolve(PostgresStore)
    task_gen = container.resolve(TaskGeneratorService)

    today = date.today()
    yesterday = today - timedelta(days=1)

    # Monday = 0 in Python weekday()
    is_monday = today.weekday() == 0
    week_start = today - timedelta(days=today.weekday())

    async with store.get_session() as session:
        result = await session.execute(
            select(PlayerProfile.patient_id)
        )
        patient_ids: List[UUID] = list(result.scalars().all())

    generated = 0
    for pid in patient_ids:
        try:
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
    from lib.models.gamification import DailyTask, PlayerProfile
    from lib.services.gamification.event_handler import GamificationEventHandler

    from lib.services.reports.meal.processor import MealStatsProcessor

    store = container.resolve(PostgresStore)
    event_handler = container.resolve(GamificationEventHandler)
    meal_processor = container.resolve(MealStatsProcessor)
    today = date.today()

    async with store.get_session() as session:
        result = await session.execute(
            select(DailyTask.patient_id)
            .where(
                DailyTask.task_date == today,
                DailyTask.task_type.in_([
                    "HIT_CALORIE_TARGET",
                    "HIT_PROTEIN_TARGET",
                ]),
                DailyTask.status == "pending",
            )
            .distinct()
        )
        patient_ids = list(result.scalars().all())

    logger.info(f"EOD macro eval for {len(patient_ids)} patients with pending macro tasks")

    evaluated = 0
    for pid in patient_ids:
        try:
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
        await lb_service.refresh_weekly_xp_board(scope="global")
        await lb_service.refresh_streak_board(scope="global")
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
    today = date.today()

    async with store.get_session() as session:
        # Find challenges that have ended
        result = await session.execute(
            select(Challenge.challenge_id).where(
                Challenge.is_active == True,
                Challenge.end_date < today,
            )
        )
        ended_ids = list(result.scalars().all())

    for cid in ended_ids:
        try:
            await challenge_service.finalize_challenge(cid)
            logger.info(f"Finalized challenge {cid}")
        except Exception:
            logger.opt(exception=True).warning(
                f"Challenge finalization failed for {cid}"
            )


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
