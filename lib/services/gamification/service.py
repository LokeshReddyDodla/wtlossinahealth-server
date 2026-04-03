"""Main gamification service — orchestrates XP, streaks, tasks, achievements."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import (
    Achievement,
    DailyTask,
    GroupMember,
    PatientAchievement,
    PlayerProfile,
    WeeklyQuest,
    XPLedgerEntry,
)
from lib.schemas.gamification import (
    AchievementResponse,
    DailyProgressResponse,
    DailyTaskResponse,
    GamificationContext,
    PlayerProfileResponse,
    TaskCompletionResponse,
    TaskStatus,
    WeeklyQuestResponse,
    XPHistoryEntry,
    XPHistoryResponse,
    title_for_level,
    xp_for_level,
)
from lib.services.gamification.achievement_evaluator import AchievementEvaluator
from lib.services.gamification.notifications import send_gamification_notification
from lib.services.gamification.time_utils import local_today
from lib.services.gamification.task_generator import TaskGeneratorService
from lib.services.gamification.xp_service import XPService, streak_multiplier
from lib.utils.postgres_session_decorator import with_postgres_session


class GamificationService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        xp_service: XPService,
        task_generator: TaskGeneratorService,
        achievement_evaluator: AchievementEvaluator,
    ) -> None:
        self.postgres_store = postgres_store
        self.xp_service = xp_service
        self.task_generator = task_generator
        self.achievement_evaluator = achievement_evaluator

    async def _post_feed_event(
        self,
        patient_id: UUID,
        event_type: str,
        event_data: Dict[str, Any],
    ) -> None:
        """Fire-and-forget feed event posting."""
        try:
            from lib.core.container import container
            from lib.services.gamification.feed_service import FeedService
            feed = container.resolve(FeedService)
            await feed.post_event(
                actor_id=patient_id,
                event_type=event_type,
                event_data=event_data,
                visibility="group",
            )
            title_map = {
                "level_up": "Level up",
                "achievement_earned": "Achievement unlocked",
                "streak_milestone": "Streak milestone",
                "challenge_completed": "Challenge completed",
                "challenge_won": "Challenge won",
            }
            body_map = {
                "level_up": f"You reached level {event_data.get('new_level')}.",
                "achievement_earned": f"You earned {event_data.get('title', 'a new achievement')}.",
                "streak_milestone": f"You're on a {event_data.get('streak')}-day streak.",
                "challenge_completed": f"You completed {event_data.get('title', 'a challenge')}.",
                "challenge_won": f"You won {event_data.get('title', 'a challenge')}.",
            }
            if event_type in title_map:
                await send_gamification_notification(
                    str(patient_id),
                    title=title_map[event_type],
                    body=body_map[event_type],
                    data={"event_type": event_type, **event_data},
                )
        except Exception as exc:
            from loguru import logger
            logger.debug(f"Feed event posting failed for {patient_id}: {exc}")

    # ── Player Profile ───────────────────────────────────────────────────

    @with_postgres_session
    async def get_or_create_profile(
        self, patient_id: UUID, *, postgres_session: AsyncSession
    ) -> PlayerProfileResponse:
        result = await postgres_session.execute(
            select(PlayerProfile).where(
                PlayerProfile.patient_id == patient_id
            )
        )
        profile = result.scalars().first()
        if not profile:
            profile = PlayerProfile(patient_id=patient_id)
            postgres_session.add(profile)
            await postgres_session.commit()
            await postgres_session.refresh(profile)

        title = title_for_level(profile.level)
        mult = streak_multiplier(profile.current_streak)
        next_level_xp = xp_for_level(profile.level + 1)
        xp_to_next = max(0, next_level_xp - profile.total_xp)

        return PlayerProfileResponse(
            player_profile_id=str(profile.player_profile_id),
            patient_id=str(profile.patient_id),
            total_xp=profile.total_xp,
            level=profile.level,
            title=title,
            current_streak=profile.current_streak,
            longest_streak=profile.longest_streak,
            streak_freezes=profile.streak_freezes,
            streak_multiplier=mult,
            last_active_date=profile.last_active_date,
            leaderboard_visibility=profile.leaderboard_visibility,
            xp_to_next_level=xp_to_next,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    @with_postgres_session
    async def update_profile(
        self,
        patient_id: UUID,
        visibility: Optional[str] = None,
        title_slug: Optional[str] = None,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        result = await postgres_session.execute(
            select(PlayerProfile).where(
                PlayerProfile.patient_id == patient_id
            )
        )
        profile = result.scalars().first()
        if not profile:
            return
        if visibility is not None:
            profile.leaderboard_visibility = visibility
        if title_slug is not None:
            profile.title_slug = title_slug
        await postgres_session.commit()

    # ── Daily Tasks ──────────────────────────────────────────────────────

    @with_postgres_session
    async def get_daily_progress(
        self,
        patient_id: UUID,
        task_date: date,
        *,
        postgres_session: AsyncSession,
    ) -> DailyProgressResponse:
        tz_name = await self._patient_timezone(patient_id, postgres_session)
        patient_today = local_today(tz_name)
        # On-demand task generation: ensure tasks exist for today
        if task_date == patient_today:
            await self.task_generator.generate_daily_tasks(patient_id, task_date)
            # Ensure weekly quest exists (on any day, not just Monday)
            week_start = task_date - timedelta(days=task_date.weekday())
            await self.task_generator.generate_weekly_quest(
                patient_id, week_start
            )

        result = await postgres_session.execute(
            select(DailyTask).where(
                DailyTask.patient_id == patient_id,
                DailyTask.task_date == task_date,
            )
        )
        tasks = result.scalars().all()

        task_responses = [
            DailyTaskResponse(
                task_id=str(t.task_id),
                task_date=t.task_date,
                task_type=t.task_type,
                title=t.title,
                description=t.description,
                source_type=t.source_type,
                target_value=t.target_value,
                current_value=t.current_value,
                status=t.status,
                xp_reward=t.xp_reward,
                bonus_multiplier=t.bonus_multiplier,
                completed_at=t.completed_at,
            )
            for t in tasks
        ]

        completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED.value)
        xp_earned = await self.xp_service.get_xp_earned_for_date(
            patient_id,
            task_date,
            tz_name=tz_name,
        )

        profile_result = await postgres_session.execute(
            select(PlayerProfile).where(
                PlayerProfile.patient_id == patient_id
            )
        )
        profile = profile_result.scalars().first()
        streak_status = "active"
        if profile:
            if profile.streak_frozen_on == task_date:
                streak_status = "frozen"
            elif profile.current_streak == 0 and profile.longest_streak > 0:
                streak_status = "broken"

        return DailyProgressResponse(
            date=task_date,
            tasks=task_responses,
            completed_count=completed,
            total_count=len(tasks),
            xp_earned_today=xp_earned,
            streak_status=streak_status,
        )

    @with_postgres_session
    async def complete_task(
        self,
        patient_id: UUID,
        task_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> TaskCompletionResponse:
        result = await postgres_session.execute(
            select(DailyTask).where(
                DailyTask.task_id == task_id,
                DailyTask.patient_id == patient_id,
            )
        )
        task = result.scalars().first()
        if not task:
            raise ValueError("Task not found")
        if task.status != TaskStatus.PENDING.value:
            raise ValueError(f"Task is not pending (status: {task.status})")

        # Only logging tasks can be manually completed — target-based tasks
        # (steps, calories, protein, workouts) must be auto-completed by
        # the event handler when the actual metric is met.
        from lib.schemas.gamification import MANUALLY_COMPLETABLE_TASKS
        if task.task_type not in MANUALLY_COMPLETABLE_TASKS:
            raise ValueError(
                f"Task type '{task.task_type}' cannot be manually completed"
            )

        task.status = TaskStatus.COMPLETED.value
        task.completed_at = datetime.now().replace(tzinfo=None)
        await postgres_session.commit()

        xp_granted, new_level, leveled_up = await self.xp_service.grant_xp(
            patient_id=patient_id,
            amount=task.xp_reward,
            source_type="task",
            source_id=task.task_id,
            description=f"Task: {task.title}",
        )

        newly_earned = await self.achievement_evaluator.evaluate_all(
            patient_id=patient_id
        )

        # Refresh profile from DB to get updated XP (grant_xp used a separate session)
        postgres_session.expire_all()
        profile_result = await postgres_session.execute(
            select(PlayerProfile).where(
                PlayerProfile.patient_id == patient_id
            )
        )
        profile = profile_result.scalars().first()

        response = TaskCompletionResponse(
            task_id=str(task.task_id),
            xp_earned=xp_granted,
            new_total_xp=profile.total_xp if profile else 0,
            level_up=leveled_up,
            new_level=new_level,
            achievements_unlocked=[
                AchievementResponse(
                    achievement_id=str(a.achievement_id),
                    slug=a.slug,
                    title=a.title,
                    description=a.description,
                    icon=a.icon,
                    category=a.category,
                    tier=a.tier,
                    xp_reward=a.xp_reward,
                    is_hidden=a.is_hidden,
                    is_progressive=a.is_progressive,
                    earned=True,
                    earned_at=datetime.now().replace(tzinfo=None),
                    progress_pct=1.0,
                )
                for a in newly_earned
            ],
        )

        # Post feed events (fire-and-forget)
        if leveled_up:
            await self._post_feed_event(
                patient_id, "level_up",
                {"new_level": new_level, "title": title_for_level(new_level)},
            )
        for a in newly_earned:
            await self._post_feed_event(
                patient_id, "achievement_earned",
                {"slug": a.slug, "title": a.title, "tier": a.tier},
            )

        return response

    # ── Achievements ─────────────────────────────────────────────────────

    @with_postgres_session
    async def get_achievements(
        self,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> List[AchievementResponse]:
        earned_result = await postgres_session.execute(
            select(PatientAchievement).where(
                PatientAchievement.patient_id == patient_id
            )
        )
        earned_map = {
            pa.achievement_id: pa for pa in earned_result.scalars().all()
        }

        all_result = await postgres_session.execute(
            select(Achievement).order_by(Achievement.sort_order)
        )
        all_achievements = all_result.scalars().all()

        responses = []
        for a in all_achievements:
            pa = earned_map.get(a.achievement_id)
            earned = pa is not None

            progress = 1.0 if earned else 0.0
            if not earned and not a.is_hidden:
                progress = await self.achievement_evaluator.get_progress(
                    patient_id, a
                )

            # Hide description for hidden achievements not yet earned
            if a.is_hidden and not earned:
                continue

            responses.append(
                AchievementResponse(
                    achievement_id=str(a.achievement_id),
                    slug=a.slug,
                    title=a.title if earned or not a.is_hidden else "???",
                    description=a.description if earned or not a.is_hidden else "Hidden achievement",
                    icon=a.icon,
                    category=a.category,
                    tier=a.tier,
                    xp_reward=a.xp_reward,
                    is_hidden=a.is_hidden,
                    is_progressive=a.is_progressive,
                    earned=earned,
                    earned_at=pa.earned_at if pa else None,
                    progress_pct=progress,
                    starred_by=str(pa.starred_by) if pa and pa.starred_by else None,
                    starred_at=pa.starred_at if pa else None,
                )
            )
        return responses

    @with_postgres_session
    async def get_recent_achievements(
        self,
        patient_id: UUID,
        limit: int = 10,
        *,
        postgres_session: AsyncSession,
    ) -> List[AchievementResponse]:
        achievements = await self.get_achievements(
            patient_id, postgres_session=postgres_session
        )
        earned = [a for a in achievements if a.earned]
        earned.sort(key=lambda a: a.earned_at or datetime.min, reverse=True)
        return earned[:limit]

    # ── Weekly Quest ─────────────────────────────────────────────────────

    @with_postgres_session
    async def get_current_quest(
        self,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[WeeklyQuestResponse]:
        today = await self._patient_today(patient_id, postgres_session)
        week_start = today - timedelta(days=today.weekday())
        result = await postgres_session.execute(
            select(WeeklyQuest).where(
                WeeklyQuest.patient_id == patient_id,
                WeeklyQuest.week_start == week_start,
            )
        )
        quest = result.scalars().first()
        if not quest:
            return None

        progress = (
            min(1.0, quest.current_value / quest.target_value)
            if quest.target_value > 0
            else 0.0
        )
        return WeeklyQuestResponse(
            quest_id=str(quest.quest_id),
            week_start=quest.week_start,
            quest_type=quest.quest_type,
            title=quest.title,
            description=quest.description,
            target_value=quest.target_value,
            current_value=quest.current_value,
            xp_reward=quest.xp_reward,
            status=quest.status,
            progress_pct=progress,
            completed_at=quest.completed_at,
        )

    # ── XP History ───────────────────────────────────────────────────────

    @with_postgres_session
    async def get_xp_history(
        self,
        patient_id: UUID,
        period: str = "week",
        *,
        postgres_session: AsyncSession,
    ) -> XPHistoryResponse:
        days = 7 if period == "week" else 30
        patient_today = await self._patient_today(patient_id, postgres_session)
        start_date = patient_today - timedelta(days=days)
        start_dt = datetime.combine(start_date, datetime.min.time())

        result = await postgres_session.execute(
            select(
                func.date(XPLedgerEntry.created_at).label("day"),
                func.sum(XPLedgerEntry.xp_amount).label("xp"),
            )
            .where(
                XPLedgerEntry.patient_id == patient_id,
                XPLedgerEntry.created_at >= start_dt,
            )
            .group_by(func.date(XPLedgerEntry.created_at))
            .order_by(func.date(XPLedgerEntry.created_at))
        )
        rows = result.all()

        tasks_result = await postgres_session.execute(
            select(
                DailyTask.task_date,
                func.count(DailyTask.task_id).label("cnt"),
            )
            .where(
                DailyTask.patient_id == patient_id,
                DailyTask.task_date >= start_date,
                DailyTask.status == TaskStatus.COMPLETED.value,
            )
            .group_by(DailyTask.task_date)
        )
        tasks_by_date = {row.task_date: row.cnt for row in tasks_result.all()}

        entries = [
            XPHistoryEntry(
                date=row.day,
                xp_earned=row.xp or 0,
                tasks_completed=tasks_by_date.get(row.day, 0),
            )
            for row in rows
        ]

        return XPHistoryResponse(
            period=period,
            entries=entries,
            total_xp_period=sum(e.xp_earned for e in entries),
        )

    @with_postgres_session
    async def use_streak_freeze(
        self,
        patient_id: UUID,
        freeze_date: Optional[date] = None,
        *,
        postgres_session: AsyncSession,
    ) -> PlayerProfileResponse:
        from lib.core.container import container
        from lib.services.gamification.streak_service import StreakService

        streak_service = container.resolve(StreakService)
        target_date = freeze_date or await self._patient_today(
            patient_id, postgres_session
        )
        await streak_service.use_freeze(
            patient_id,
            target_date,
            postgres_session=postgres_session,
        )
        return await self.get_or_create_profile(
            patient_id, postgres_session=postgres_session
        )

    # ── AI Context ───────────────────────────────────────────────────────

    @with_postgres_session
    async def get_gamification_context(
        self,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> GamificationContext:
        """Build the gamification context block for the AI agent."""
        profile_result = await postgres_session.execute(
            select(PlayerProfile).where(
                PlayerProfile.patient_id == patient_id
            )
        )
        profile = profile_result.scalars().first()
        if not profile:
            return GamificationContext(
                level=1,
                title="Newcomer",
                total_xp=0,
                current_streak=0,
                streak_multiplier=1.0,
                streak_freezes=1,
            )

        # Recent achievements
        earned_result = await postgres_session.execute(
            select(PatientAchievement, Achievement)
            .join(Achievement)
            .where(PatientAchievement.patient_id == patient_id)
            .order_by(PatientAchievement.earned_at.desc())
            .limit(5)
        )
        recent = [row.Achievement.slug for row in earned_result.all()]

        # Today's tasks
        today = await self._patient_today(patient_id, postgres_session)
        task_result = await postgres_session.execute(
            select(DailyTask).where(
                DailyTask.patient_id == patient_id,
                DailyTask.task_date == today,
            )
        )
        tasks = task_result.scalars().all()
        completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED.value)

        # Weekly quest
        week_start = today - timedelta(days=today.weekday())
        quest_result = await postgres_session.execute(
            select(WeeklyQuest).where(
                WeeklyQuest.patient_id == patient_id,
                WeeklyQuest.week_start == week_start,
            )
        )
        quest = quest_result.scalars().first()
        quest_data = None
        if quest:
            quest_data = {
                "title": quest.title,
                "progress": f"{int(quest.current_value)}/{int(quest.target_value)}",
                "status": quest.status,
            }

        # Buddy streak (best active buddy)
        from sqlalchemy import or_
        from lib.models.gamification import Buddy

        buddy_result = await postgres_session.execute(
            select(func.max(Buddy.buddy_streak)).where(
                Buddy.status == "active",
                or_(
                    Buddy.requester_id == patient_id,
                    Buddy.accepter_id == patient_id,
                ),
            )
        )
        buddy_streak = buddy_result.scalar()

        # Active challenges
        from lib.models.gamification import Challenge, ChallengeParticipant
        direct_challenges_result = await postgres_session.execute(
            select(ChallengeParticipant, Challenge)
            .join(Challenge)
            .where(
                ChallengeParticipant.participant_id == patient_id,
                ChallengeParticipant.participant_type == "patient",
                ChallengeParticipant.status == "active",
                Challenge.is_active == True,
            )
            .limit(5)
        )
        direct_challenge_rows = list(direct_challenges_result.all())

        group_ids_result = await postgres_session.execute(
            select(GroupMember.group_id).where(
                GroupMember.patient_id == patient_id,
                GroupMember.is_active == True,
            )
        )
        group_ids = list(group_ids_result.scalars().all())
        group_challenge_rows = []
        if group_ids:
            group_challenges_result = await postgres_session.execute(
                select(ChallengeParticipant, Challenge)
                .join(Challenge)
                .where(
                    ChallengeParticipant.participant_id.in_(group_ids),
                    ChallengeParticipant.participant_type == "group",
                    ChallengeParticipant.status == "active",
                    Challenge.is_active == True,
                )
                .limit(5)
            )
            group_challenge_rows = list(group_challenges_result.all())

        active_challenges = [
            {
                "title": row.Challenge.title,
                "rank": row.ChallengeParticipant.rank,
                "progress": f"{row.ChallengeParticipant.current_value:.0f}/{row.Challenge.target_value:.0f}",
            }
            for row in (direct_challenge_rows + group_challenge_rows)[:5]
        ]

        return GamificationContext(
            level=profile.level,
            title=title_for_level(profile.level),
            total_xp=profile.total_xp,
            current_streak=profile.current_streak,
            streak_multiplier=streak_multiplier(profile.current_streak),
            streak_freezes=profile.streak_freezes,
            recent_achievements=recent,
            tasks_today={"completed": completed, "total": len(tasks)},
            weekly_quest=quest_data,
            active_challenges=active_challenges,
            buddy_streak=buddy_streak,
        )

    async def _patient_today(
        self,
        patient_id: UUID,
        postgres_session: AsyncSession,
    ) -> date:
        return local_today(await self._patient_timezone(patient_id, postgres_session))

    @with_postgres_session
    async def get_patient_local_date(
        self,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> date:
        return await self._patient_today(patient_id, postgres_session)

    async def _patient_timezone(
        self, patient_id: UUID, postgres_session: AsyncSession
    ) -> str | None:
        from lib.services.gamification.time_utils import get_patient_timezone
        return await get_patient_timezone(patient_id, postgres_session)
