"""Cron job definitions for gamification background tasks."""

from arq.cron import cron

from lib.workers.tasks.gamification.tasks import (
    cleanup_feed_and_leaderboards,
    evaluate_eod_macros,
    generate_daily_tasks_for_all,
    process_challenge_lifecycle,
    process_streaks_for_all,
    refresh_leaderboards,
)

GAMIFICATION_CRON_JOBS = [
    # Nightly streak processor — 2:00 AM IST (20:30 UTC previous day)
    cron(
        process_streaks_for_all,
        hour=20,
        minute=30,
        timeout=3600,
        unique=True,
    ),
    # Daily task generator — 5:00 AM IST (23:30 UTC previous day)
    cron(
        generate_daily_tasks_for_all,
        hour=23,
        minute=30,
        timeout=3600,
        unique=True,
    ),
    # EOD macro evaluator — 11:00 PM IST (17:30 UTC)
    cron(
        evaluate_eod_macros,
        hour=17,
        minute=30,
        timeout=1800,
        unique=True,
    ),
    # Leaderboard refresh — every 15 minutes
    cron(
        refresh_leaderboards,
        minute={0, 15, 30, 45},
        timeout=300,
        unique=True,
    ),
    # Challenge lifecycle — every hour
    cron(
        process_challenge_lifecycle,
        minute=10,
        timeout=600,
        unique=True,
    ),
    # Feed + leaderboard cleanup — 3:00 AM IST (21:30 UTC)
    cron(
        cleanup_feed_and_leaderboards,
        hour=21,
        minute=30,
        timeout=600,
        unique=True,
    ),
]
