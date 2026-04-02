"""Achievement criteria evaluation and granting."""

from __future__ import annotations

from datetime import date, datetime, timedelta
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
from lib.schemas.gamification import TaskStatus
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

    async def _check_criteria(
        self,
        patient_id: UUID,
        achievement: Achievement,
        session: AsyncSession,
    ) -> bool:
        ct = achievement.criteria_type
        threshold = achievement.criteria_threshold

        if ct == "streak_days":
            return await self._check_streak(patient_id, threshold, session)
        if ct == "tasks_completed":
            return await self._check_tasks_completed(
                patient_id, threshold, session
            )
        if ct == "meals_logged":
            return await self._check_task_type_count(
                patient_id, "LOG_MEAL", threshold, session
            )
        if ct == "steps_hit":
            return await self._check_task_type_count(
                patient_id, "HIT_STEP_GOAL", threshold, session
            )
        if ct == "workouts_completed":
            return await self._check_task_type_count(
                patient_id, "COMPLETE_WORKOUT", threshold, session
            )
        if ct == "mood_logged":
            return await self._check_task_type_count(
                patient_id, "LOG_MOOD", threshold, session
            )
        if ct == "sleep_logged":
            return await self._check_task_type_count(
                patient_id, "LOG_SLEEP", threshold, session
            )
        if ct == "total_xp":
            return await self._check_total_xp(patient_id, threshold, session)
        if ct == "level_reached":
            return await self._check_level(patient_id, threshold, session)
        if ct == "buddy_added":
            return await self._check_buddy_count(
                patient_id, threshold, session
            )
        if ct == "cheers_sent":
            return await self._check_cheers_sent(
                patient_id, threshold, session
            )
        if ct == "group_challenges_completed":
            return await self._check_group_challenges(
                patient_id, threshold, session
            )
        if ct == "buddy_streak":
            return await self._check_buddy_streak(
                patient_id, threshold, session
            )
        if ct == "macro_hit_streak":
            return await self._check_consecutive_task_type(
                patient_id, "HIT_CALORIE_TARGET", threshold, session
            )
        if ct == "monthly_active_days":
            return await self._check_monthly_active(
                patient_id, threshold, session
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
            # Logged something between 2-4 AM
            result = await session.execute(
                select(func.count(DailyTask.task_id)).where(
                    DailyTask.patient_id == patient_id,
                    DailyTask.status == TaskStatus.COMPLETED.value,
                    func.extract("hour", DailyTask.completed_at).between(2, 4),
                )
            )
            return (result.scalar() or 0) >= threshold

        if slug == "comeback_kid":
            # Has longest_streak > 0 AND current_streak >= 3 (rebuilt after a break)
            result = await session.execute(
                select(PlayerProfile).where(
                    PlayerProfile.patient_id == patient_id
                )
            )
            profile = result.scalars().first()
            if not profile:
                return False
            return profile.longest_streak > profile.current_streak >= 3

        if slug == "perfect_week":
            # All plan-derived tasks completed for 7 consecutive days
            today = date.today()
            for offset in range(7):
                d = today - timedelta(days=offset)
                day_result = await session.execute(
                    select(DailyTask).where(
                        DailyTask.patient_id == patient_id,
                        DailyTask.task_date == d,
                        DailyTask.source_type.in_(["diet_plan", "fitness_plan"]),
                        DailyTask.status != TaskStatus.COMPLETED.value,
                    )
                )
                if day_result.scalars().first():
                    return False
            return True

        if slug == "early_bird":
            # Logged before 6 AM on N days
            result = await session.execute(
                select(func.count(func.distinct(DailyTask.task_date))).where(
                    DailyTask.patient_id == patient_id,
                    DailyTask.status == TaskStatus.COMPLETED.value,
                    func.extract("hour", DailyTask.completed_at) < 6,
                )
            )
            return (result.scalar() or 0) >= threshold

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
        result = await session.execute(
            select(func.count(ChallengeParticipant.id)).where(
                ChallengeParticipant.participant_id == patient_id,
                ChallengeParticipant.participant_type == "patient",
                ChallengeParticipant.status == "completed",
            )
        )
        count = result.scalar() or 0
        return count >= threshold

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
        """Check if patient was active 25+ days in any calendar month."""
        today = date.today()
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
