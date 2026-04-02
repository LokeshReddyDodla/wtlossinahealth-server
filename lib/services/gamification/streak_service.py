"""Streak computation, freeze logic, and buddy streak tracking."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import (
    Buddy,
    DailyTask,
    PlayerProfile,
)
from lib.schemas.gamification import TaskStatus
from lib.utils.postgres_session_decorator import with_postgres_session

# A day is "active" if the patient completed at least 2 of these task types.
ACTIVITY_TASK_TYPES = {
    "LOG_MEAL",
    "LOG_SLEEP",
    "LOG_MOOD",
    "LOG_GLUCOSE",
    "HIT_STEP_GOAL",
    "COMPLETE_WORKOUT",
}
ACTIVITY_THRESHOLD = 2


class StreakService:
    def __init__(self, postgres_store: PostgresStore) -> None:
        self.postgres_store = postgres_store

    @with_postgres_session
    async def process_streak(
        self,
        patient_id: UUID,
        for_date: date,
        *,
        postgres_session: AsyncSession,
    ) -> dict:
        """Evaluate streak for the given date. Returns summary dict."""
        profile = await self._get_or_create_profile(
            patient_id, postgres_session
        )

        if profile.last_active_date == for_date:
            return {"action": "already_processed", "streak": profile.current_streak}

        was_active = await self._was_active(
            patient_id, for_date, postgres_session
        )

        if was_active:
            # Only continue the streak if for_date is the day after last_active_date
            # (or if there's no history yet, i.e., first active day)
            is_consecutive = (
                profile.last_active_date is None
                or (for_date - profile.last_active_date).days == 1
                or (
                    profile.streak_frozen_on is not None
                    and (for_date - profile.streak_frozen_on).days == 1
                )
            )
            if is_consecutive:
                profile.current_streak += 1
            else:
                # Gap too large — reset and start fresh
                profile.current_streak = 1
            if profile.current_streak > profile.longest_streak:
                profile.longest_streak = profile.current_streak
            profile.last_active_date = for_date
            profile.streak_frozen_on = None  # Clear stale freeze date

            # Earn a freeze every 7 streak days (max 3)
            if profile.current_streak % 7 == 0 and profile.streak_freezes < 3:
                profile.streak_freezes += 1

            await postgres_session.commit()

            # Post feed event for streak milestones
            streak = profile.current_streak
            if streak in (7, 14, 30, 60, 90):
                try:
                    from lib.core.container import container
                    from lib.services.gamification.feed_service import FeedService
                    feed = container.resolve(FeedService)
                    await feed.post_event(
                        actor_id=patient_id,
                        event_type="streak_milestone",
                        event_data={"streak": streak},
                        visibility="group",
                    )
                except Exception:
                    pass

            return {"action": "incremented", "streak": profile.current_streak}

        # Not active — try freeze
        if profile.streak_freezes > 0 and profile.current_streak > 0:
            profile.streak_freezes -= 1
            profile.streak_frozen_on = for_date
            await postgres_session.commit()
            return {
                "action": "frozen",
                "streak": profile.current_streak,
                "freezes_remaining": profile.streak_freezes,
            }

        # Streak broken
        old_streak = profile.current_streak
        profile.current_streak = 0
        profile.streak_frozen_on = None
        await postgres_session.commit()
        return {
            "action": "broken",
            "old_streak": old_streak,
            "streak": 0,
        }

    @with_postgres_session
    async def process_buddy_streaks(
        self,
        patient_id: UUID,
        for_date: date,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        """Update buddy_streak for all active buddies of this patient."""
        result = await postgres_session.execute(
            select(Buddy).where(
                Buddy.status == "active",
                or_(
                    Buddy.requester_id == patient_id,
                    Buddy.accepter_id == patient_id,
                ),
            )
        )
        buddies = result.scalars().all()

        my_active = await self._was_active(
            patient_id, for_date, postgres_session
        )

        for buddy in buddies:
            other_id = (
                buddy.accepter_id
                if buddy.requester_id == patient_id
                else buddy.requester_id
            )
            other_active = await self._was_active(
                other_id, for_date, postgres_session
            )

            if my_active and other_active:
                if buddy.last_both_active != for_date:
                    buddy.buddy_streak += 1
                    if buddy.buddy_streak > buddy.buddy_streak_longest:
                        buddy.buddy_streak_longest = buddy.buddy_streak
                    buddy.last_both_active = for_date
            else:
                if buddy.buddy_streak > 0:
                    buddy.buddy_streak = 0

        await postgres_session.commit()

    async def _was_active(
        self,
        patient_id: UUID,
        for_date: date,
        session: AsyncSession,
    ) -> bool:
        """Check if the patient completed >= ACTIVITY_THRESHOLD tasks on for_date."""
        result = await session.execute(
            select(DailyTask.task_type)
            .where(
                DailyTask.patient_id == patient_id,
                DailyTask.task_date == for_date,
                DailyTask.status == TaskStatus.COMPLETED.value,
                DailyTask.task_type.in_(ACTIVITY_TASK_TYPES),
            )
            .distinct()
        )
        distinct_types = result.scalars().all()
        return len(distinct_types) >= ACTIVITY_THRESHOLD

    async def _get_or_create_profile(
        self, patient_id: UUID, session: AsyncSession
    ) -> PlayerProfile:
        result = await session.execute(
            select(PlayerProfile).where(PlayerProfile.patient_id == patient_id)
        )
        profile = result.scalars().first()
        if profile:
            return profile
        try:
            profile = PlayerProfile(patient_id=patient_id)
            session.add(profile)
            await session.flush()
            return profile
        except Exception:
            await session.rollback()
            result = await session.execute(
                select(PlayerProfile).where(PlayerProfile.patient_id == patient_id)
            )
            profile = result.scalars().first()
            if profile:
                return profile
            raise
