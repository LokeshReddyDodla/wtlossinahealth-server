"""Cron job definitions for gamification background tasks."""

from arq.cron import cron

from lib.workers.tasks.gamification.tasks import (
    cleanup_feed_and_leaderboards,
    evaluate_eod_macros,
    generate_daily_tasks_for_all,
    process_challenge_lifecycle,
    process_streaks_for_all,
    refresh_leaderboards,
    send_streak_reminders,
)

GAMIFICATION_CRON_JOBS = [
    # Run hourly; worker filters by patient-local 2:00 AM.
    cron(
        process_streaks_for_all,
        minute=5,
        timeout=3600,
        unique=True,
    ),
    # Run hourly; worker filters by patient-local 5:00 AM.
    cron(
        generate_daily_tasks_for_all,
        minute=10,
        timeout=3600,
        unique=True,
    ),
    # Run hourly; worker filters by patient-local 11:00 PM.
    cron(
        evaluate_eod_macros,
        minute=15,
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
    # Run hourly; worker filters by patient-local 8:00 PM.
    cron(
        send_streak_reminders,
        minute=25,
        timeout=1800,
        unique=True,
    ),
    # Feed + leaderboard cleanup — daily
    cron(
        cleanup_feed_and_leaderboards,
        hour=0,
        minute=20,
        timeout=600,
        unique=True,
    ),
]
