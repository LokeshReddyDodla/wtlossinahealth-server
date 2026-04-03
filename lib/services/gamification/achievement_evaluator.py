"""Achievement criteria evaluation and granting."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import (
    Achievement,
    Buddy,
    ChallengeParticipant,
    DailyTask,
    PatientAchievement,
    PlayerProfile,
)
from lib.models.patient import Patient
from lib.schemas.gamification import TaskStatus
from lib.services.gamification.time_utils import local_today, resolve_timezone
from lib.services.gamification.xp_service import XPService
from lib.utils.postgres_session_decorator import with_postgres_session


class AchievementEvaluator:
    def __init__(
        self,
        postgres_store: PostgresStore,
        xp_service: XPService,
    ) -> None:
        self.postgres_store = postgres_store
        self.xp_service = xp_service

    @with_postgres_session
    async def evaluate_all(
        self,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> List[Achievement]:
        """Check all unearned achievements and grant any that are met."""
        earned_result = await postgres_session.execute(
            select(PatientAchievement.achievement_id).where(
                PatientAchievement.patient_id == patient_id
            )
        )
        earned_ids = set(earned_result.scalars().all())

        all_result = await postgres_session.execute(select(Achievement))
        all_achievements = all_result.scalars().all()

        newly_earned: List[Achievement] = []
        for achievement in all_achievements:
            if achievement.achievement_id in earned_ids:
                continue
            if await self._check_criteria(
                patient_id, achievement, postgres_session
            ):
                pa = PatientAchievement(
                    patient_id=patient_id,
                    achievement_id=achievement.achievement_id,
                    earned_at=datetime.now().replace(tzinfo=None),
                )
                postgres_session.add(pa)
                newly_earned.append(achievement)

        if newly_earned:
            await postgres_session.commit()

        # Grant XP for each achievement (outside the main transaction)
        for achievement in newly_earned:
            await self.xp_service.grant_xp(
                patient_id=patient_id,
                amount=achievement.xp_reward,
                source_type="achievement",
                source_id=achievement.achievement_id,
                description=f"Achievement: {achievement.title}",
                respect_cap=False,
            )

        return newly_earned

    # Dispatch table: criteria_type → checker method name (or task_type for count-based)
    _TASK_COUNT_CRITERIA = {
        "meals_logged": "LOG_MEAL",
        "steps_hit": "HIT_STEP_GOAL",
        "workouts_completed": "COMPLETE_WORKOUT",
        "mood_logged": "LOG_MOOD",
        "sleep_logged": "LOG_SLEEP",
    }

    async def _check_criteria(
        self,
        patient_id: UUID,
        achievement: Achievement,
        session: AsyncSession,
    ) -> bool:
        ct = achievement.criteria_type
        threshold = achievement.criteria_threshold

        # Task-count based criteria (all follow the same pattern)
        if ct in self._TASK_COUNT_CRITERIA:
            return await self._check_task_type_count(
                patient_id, self._TASK_COUNT_CRITERIA[ct], threshold, session
            )

        dispatch = {
            "streak_days": self._check_streak,
            "tasks_completed": self._check_tasks_completed,
            "total_xp": self._check_total_xp,
            "level_reached": self._check_level,
            "buddy_added": self._check_buddy_count,
            "cheers_sent": self._check_cheers_sent,
            "group_challenges_completed": self._check_group_challenges,
            "buddy_streak": self._check_buddy_streak,
            "monthly_active_days": self._check_monthly_active,
        }
        handler = dispatch.get(ct)
        if handler:
            return await handler(patient_id, threshold, session)

        if ct == "macro_hit_streak":
            return await self._check_consecutive_task_type(
                patient_id, "HIT_CALORIE_TARGET", threshold, session
            )
        if ct == "custom":
            return await self._check_custom(
                patient_id, achievement.slug, threshold, session
            )
        return False

    async def _check_custom(
        self,
        patient_id: UUID,
        slug: str,
        threshold: int,
        session: AsyncSession,
    ) -> bool:
        """Handle custom achievement criteria by slug."""
        if slug == "night_owl":
            from lib.ai_foundation.agents.proactive_monitor.scheduling import DEFAULT_TIMEZONE
            server_tz = resolve_timezone(DEFAULT_TIMEZONE)
            patient_tz = resolve_timezone(await self._patient_timezone(patient_id, session))
            result = await session.execute(
                select(DailyTask.completed_at).where(
                    DailyTask.patient_id == patient_id,
                    DailyTask.status == TaskStatus.COMPLETED.value,
                    DailyTask.completed_at.is_not(None),
                )
            )
            count = sum(
                1
                for completed_at in result.scalars().all()
                if completed_at.replace(tzinfo=server_tz).astimezone(patient_tz).hour in {2, 3, 4}
            )
            return count >= threshold

        if slug == "comeback_kid":
            # Had at least one streak reset AND rebuilt to 3+ days
            result = await session.execute(
                select(PlayerProfile).where(
                    PlayerProfile.patient_id == patient_id
                )
            )
            profile = result.scalars().first()
            if not profile:
                return False
            return profile.streak_resets >= 1 and profile.current_streak >= 3

        if slug == "perfect_week":
            # All plan-derived tasks completed for the current ISO week (Mon-Sun)
            today = local_today(await self._patient_timezone(patient_id, session))
            week_start = today - timedelta(days=today.weekday())  # Monday
            # Only check if we're at least on Sunday (full week available)
            days_in_week = min(7, (today - week_start).days + 1)
            if days_in_week < 7:
                return False  # Week not complete yet
            for offset in range(7):
                d = week_start + timedelta(days=offset)
                day_result = await session.execute(
                    select(DailyTask).where(
                        DailyTask.patient_id == patient_id,
                        DailyTask.task_date == d,
                        DailyTask.source_type.in_(["diet_plan", "fitness_plan"]),
                    )
                )
                day_tasks = day_result.scalars().all()
                # Day must have at least one plan task AND all must be completed
                if not day_tasks:
                    return False
                if any(t.status != TaskStatus.COMPLETED.value for t in day_tasks):
                    return False
            return True

        if slug == "early_bird":
            from lib.ai_foundation.agents.proactive_monitor.scheduling import DEFAULT_TIMEZONE
            server_tz = resolve_timezone(DEFAULT_TIMEZONE)
            patient_tz = resolve_timezone(await self._patient_timezone(patient_id, session))
            result = await session.execute(
                select(DailyTask.task_date, DailyTask.completed_at).where(
                    DailyTask.patient_id == patient_id,
                    DailyTask.status == TaskStatus.COMPLETED.value,
                    DailyTask.completed_at.is_not(None),
                )
            )
            early_days = {
                task_date
                for task_date, completed_at in result.all()
                if completed_at.replace(tzinfo=server_tz).astimezone(patient_tz).hour < 6
            }
            return len(early_days) >= threshold

        if slug == "social_butterfly":
            # In 3+ active groups
            from lib.models.gamification import GroupMember
            result = await session.execute(
                select(func.count(GroupMember.id)).where(
                    GroupMember.patient_id == patient_id,
                    GroupMember.is_active == True,
                )
            )
            return (result.scalar() or 0) >= threshold

        return False

    async def _check_streak(
        self, patient_id: UUID, threshold: int, session: AsyncSession
    ) -> bool:
        result = await session.execute(
            select(PlayerProfile.current_streak).where(
                PlayerProfile.patient_id == patient_id
            )
        )
        streak = result.scalar()
        return streak is not None and streak >= threshold

    async def _check_tasks_completed(
        self, patient_id: UUID, threshold: int, session: AsyncSession
    ) -> bool:
        result = await session.execute(
            select(func.count(DailyTask.task_id)).where(
                DailyTask.patient_id == patient_id,
                DailyTask.status == TaskStatus.COMPLETED.value,
            )
        )
        count = result.scalar() or 0
        return count >= threshold

    async def _check_task_type_count(
        self,
        patient_id: UUID,
        task_type: str,
        threshold: int,
        session: AsyncSession,
    ) -> bool:
        result = await session.execute(
            select(func.count(DailyTask.task_id)).where(
                DailyTask.patient_id == patient_id,
                DailyTask.task_type == task_type,
                DailyTask.status == TaskStatus.COMPLETED.value,
            )
        )
        count = result.scalar() or 0
        return count >= threshold

    async def _check_total_xp(
        self, patient_id: UUID, threshold: int, session: AsyncSession
    ) -> bool:
        result = await session.execute(
            select(PlayerProfile.total_xp).where(
                PlayerProfile.patient_id == patient_id
            )
        )
        xp = result.scalar()
        return xp is not None and xp >= threshold

    async def _check_level(
        self, patient_id: UUID, threshold: int, session: AsyncSession
    ) -> bool:
        result = await session.execute(
            select(PlayerProfile.level).where(
                PlayerProfile.patient_id == patient_id
            )
        )
        level = result.scalar()
        return level is not None and level >= threshold

    async def _check_buddy_count(
        self, patient_id: UUID, threshold: int, session: AsyncSession
    ) -> bool:
        from sqlalchemy import or_

        result = await session.execute(
            select(func.count(Buddy.buddy_id)).where(
                Buddy.status == "active",
                or_(
                    Buddy.requester_id == patient_id,
                    Buddy.accepter_id == patient_id,
                ),
            )
        )
        count = result.scalar() or 0
        return count >= threshold

    async def _check_cheers_sent(
        self, patient_id: UUID, threshold: int, session: AsyncSession
    ) -> bool:
        from lib.models.gamification import Cheer

        result = await session.execute(
            select(func.count(Cheer.cheer_id)).where(
                Cheer.sender_id == patient_id
            )
        )
        count = result.scalar() or 0
        return count >= threshold

    async def _check_group_challenges(
        self, patient_id: UUID, threshold: int, session: AsyncSession
    ) -> bool:
        patient_result = await session.execute(
            select(func.count(ChallengeParticipant.id)).where(
                ChallengeParticipant.participant_id == patient_id,
                ChallengeParticipant.participant_type == "patient",
                ChallengeParticipant.status == "completed",
            )
        )
        patient_count = patient_result.scalar() or 0

        from lib.models.gamification import GroupMember

        group_ids_result = await session.execute(
            select(GroupMember.group_id).where(
                GroupMember.patient_id == patient_id,
                GroupMember.is_active == True,
            )
        )
        group_ids = list(group_ids_result.scalars().all())
        group_count = 0
        if group_ids:
            group_result = await session.execute(
                select(func.count(ChallengeParticipant.id)).where(
                    ChallengeParticipant.participant_id.in_(group_ids),
                    ChallengeParticipant.participant_type == "group",
                    ChallengeParticipant.status == "completed",
                )
            )
            group_count = group_result.scalar() or 0

        return (patient_count + group_count) >= threshold

    async def _check_buddy_streak(
        self, patient_id: UUID, threshold: int, session: AsyncSession
    ) -> bool:
        from sqlalchemy import or_

        result = await session.execute(
            select(func.max(Buddy.buddy_streak)).where(
                Buddy.status == "active",
                or_(
                    Buddy.requester_id == patient_id,
                    Buddy.accepter_id == patient_id,
                ),
            )
        )
        max_streak = result.scalar()
        return max_streak is not None and max_streak >= threshold

    async def _check_consecutive_task_type(
        self,
        patient_id: UUID,
        task_type: str,
        threshold: int,
        session: AsyncSession,
    ) -> bool:
        """Check if the patient has completed a task type on N consecutive days."""
        result = await session.execute(
            select(DailyTask.task_date)
            .where(
                DailyTask.patient_id == patient_id,
                DailyTask.task_type == task_type,
                DailyTask.status == TaskStatus.COMPLETED.value,
            )
            .order_by(DailyTask.task_date.desc())
            .limit(threshold)
        )
        dates = sorted(result.scalars().all())
        if len(dates) < threshold:
            return False
        # Check if the last N dates are consecutive
        for i in range(1, len(dates)):
            if (dates[i] - dates[i - 1]).days != 1:
                return False
        return True

    async def _check_monthly_active(
        self, patient_id: UUID, threshold: int, session: AsyncSession
    ) -> bool:
        """Check if patient was active 25+ days in the current calendar month.

        NOTE: Only checks the current month, not historical months.
        The achievement triggers when the threshold is met this month.
        """
        today = local_today(await self._patient_timezone(patient_id, session))
        first_of_month = today.replace(day=1)
        result = await session.execute(
            select(func.count(func.distinct(DailyTask.task_date))).where(
                DailyTask.patient_id == patient_id,
                DailyTask.task_date >= first_of_month,
                DailyTask.status == TaskStatus.COMPLETED.value,
            )
        )
        count = result.scalar() or 0
        return count >= threshold

    async def _patient_timezone(
        self, patient_id: UUID, session: AsyncSession
    ) -> str | None:
        from lib.services.gamification.time_utils import get_patient_timezone
        return await get_patient_timezone(patient_id, session)

    @with_postgres_session
    async def get_progress(
        self,
        patient_id: UUID,
        achievement: Achievement,
        *,
        postgres_session: AsyncSession,
    ) -> float:
        """Return progress as 0.0 - 1.0 for a specific achievement."""
        threshold = achievement.criteria_threshold
        if threshold <= 0:
            return 1.0

        ct = achievement.criteria_type
        current = 0

        if ct == "streak_days":
            result = await postgres_session.execute(
                select(PlayerProfile.current_streak).where(
                    PlayerProfile.patient_id == patient_id
                )
            )
            current = result.scalar() or 0
        elif ct == "tasks_completed":
            result = await postgres_session.execute(
                select(func.count(DailyTask.task_id)).where(
                    DailyTask.patient_id == patient_id,
                    DailyTask.status == TaskStatus.COMPLETED.value,
                )
            )
            current = result.scalar() or 0
        elif ct == "total_xp":
            result = await postgres_session.execute(
                select(PlayerProfile.total_xp).where(
                    PlayerProfile.patient_id == patient_id
                )
            )
            current = result.scalar() or 0
        elif ct == "level_reached":
            result = await postgres_session.execute(
                select(PlayerProfile.level).where(
                    PlayerProfile.patient_id == patient_id
                )
            )
            current = result.scalar() or 0
        elif ct in ("meals_logged", "steps_hit", "workouts_completed", "mood_logged", "sleep_logged"):
            type_map = {
                "meals_logged": "LOG_MEAL",
                "steps_hit": "HIT_STEP_GOAL",
                "workouts_completed": "COMPLETE_WORKOUT",
                "mood_logged": "LOG_MOOD",
                "sleep_logged": "LOG_SLEEP",
            }
            result = await postgres_session.execute(
                select(func.count(DailyTask.task_id)).where(
                    DailyTask.patient_id == patient_id,
                    DailyTask.task_type == type_map[ct],
                    DailyTask.status == TaskStatus.COMPLETED.value,
                )
            )
            current = result.scalar() or 0
        elif ct == "buddy_added":
            from sqlalchemy import or_
            result = await postgres_session.execute(
                select(func.count(Buddy.buddy_id)).where(
                    Buddy.status == "active",
                    or_(
                        Buddy.requester_id == patient_id,
                        Buddy.accepter_id == patient_id,
                    ),
                )
            )
            current = result.scalar() or 0
        elif ct == "cheers_sent":
            from lib.models.gamification import Cheer
            result = await postgres_session.execute(
                select(func.count(Cheer.cheer_id)).where(
                    Cheer.sender_id == patient_id
                )
            )
            current = result.scalar() or 0
        elif ct == "group_challenges_completed":
            result = await postgres_session.execute(
                select(func.count(ChallengeParticipant.id)).where(
                    ChallengeParticipant.participant_id == patient_id,
                    ChallengeParticipant.participant_type == "patient",
                    ChallengeParticipant.status == "completed",
                )
            )
            current = result.scalar() or 0

        return min(1.0, current / threshold)
