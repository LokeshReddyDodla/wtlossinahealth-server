"""Fire-and-forget hooks for gamification events from existing services."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional
from uuid import UUID

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import DailyTask
from lib.schemas.gamification import TaskStatus, TaskType
from lib.services.gamification.achievement_evaluator import AchievementEvaluator
from lib.services.gamification.time_utils import local_today
from lib.services.gamification.xp_service import XPService
from lib.utils.postgres_session_decorator import with_postgres_session


class GamificationEventHandler:
    def __init__(
        self,
        postgres_store: PostgresStore,
        xp_service: XPService,
        achievement_evaluator: AchievementEvaluator,
    ) -> None:
        self.postgres_store = postgres_store
        self.xp_service = xp_service
        self.achievement_evaluator = achievement_evaluator
        self._tz_cache: dict[UUID, str | None] = {}  # patient_id -> timezone name

    async def _ensure_tasks_exist(self, patient_id: UUID) -> None:
        """Ensure daily tasks exist before trying to complete them."""
        from lib.services.gamification.task_generator import TaskGeneratorService
        from lib.core.container import container
        task_gen = container.resolve(TaskGeneratorService)
        await task_gen.generate_daily_tasks(
            patient_id, await self._patient_today(patient_id)
        )

    async def _safe_complete(
        self, patient_id: UUID, task_type: TaskType, hook_name: str
    ) -> None:
        """Fire-and-forget wrapper: complete a task and log on failure."""
        try:
            await self._complete_task(patient_id, task_type.value)
        except Exception:
            logger.opt(exception=True).warning(
                f"Gamification hook {hook_name} failed for {patient_id}"
            )

    async def on_meal_logged(self, patient_id: UUID) -> None:
        try:
            await self._increment_challenge_metric(
                patient_id, metric_type="meals_logged", increment=1.0,
            )
        except Exception:
            pass
        await self._safe_complete(patient_id, TaskType.LOG_MEAL, "on_meal_logged")
        await self._refresh_macro_progress(patient_id)

    async def on_sleep_logged(self, patient_id: UUID) -> None:
        await self._safe_complete(patient_id, TaskType.LOG_SLEEP, "on_sleep_logged")

    async def on_mood_logged(self, patient_id: UUID) -> None:
        await self._safe_complete(patient_id, TaskType.LOG_MOOD, "on_mood_logged")

    async def on_glucose_synced(self, patient_id: UUID) -> None:
        await self._safe_complete(patient_id, TaskType.LOG_GLUCOSE, "on_glucose_synced")

    async def on_weight_logged(self, patient_id: UUID) -> None:
        await self._safe_complete(patient_id, TaskType.LOG_WEIGHT, "on_weight_logged")

    async def on_fitness_synced(
        self,
        patient_id: UUID,
        steps: Optional[float] = None,
        workout_completed: bool = False,
    ) -> None:
        try:
            if steps is not None:
                await self._evaluate_step_goal(patient_id, steps)
            if workout_completed:
                await self._increment_challenge_metric(
                    patient_id,
                    metric_type="workouts",
                    increment=1.0,
                )
                await self._complete_task(
                    patient_id, TaskType.COMPLETE_WORKOUT.value
                )
        except Exception:
            logger.opt(exception=True).warning(
                f"Gamification hook on_fitness_synced failed for {patient_id}"
            )

    async def on_macro_data_available(
        self,
        patient_id: UUID,
        total_calories: Optional[float] = None,
        total_protein: Optional[float] = None,
    ) -> None:
        """Called by EOD evaluator when daily macro totals are available."""
        from lib.schemas.gamification import CALORIE_TOLERANCE_PCT, PROTEIN_TOLERANCE_PCT
        try:
            if total_calories is not None:
                await self._evaluate_range_target(
                    patient_id, total_calories,
                    TaskType.HIT_CALORIE_TARGET,
                    1 - CALORIE_TOLERANCE_PCT, 1 + CALORIE_TOLERANCE_PCT,
                )
            if total_protein is not None:
                await self._evaluate_range_target(
                    patient_id, total_protein,
                    TaskType.HIT_PROTEIN_TARGET,
                    1 - PROTEIN_TOLERANCE_PCT, 1 + PROTEIN_TOLERANCE_PCT,
                )
        except Exception:
            logger.opt(exception=True).warning(
                f"Gamification hook on_macro_data failed for {patient_id}"
            )

    @with_postgres_session
    async def _complete_task(
        self,
        patient_id: UUID,
        task_type: str,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        today = await self._patient_today(patient_id)

        # Ensure tasks exist (on-demand for mid-day signups)
        await self._ensure_tasks_exist(patient_id)

        result = await postgres_session.execute(
            select(DailyTask).where(
                DailyTask.patient_id == patient_id,
                DailyTask.task_date == today,
                DailyTask.task_type == task_type,
                DailyTask.status == TaskStatus.PENDING.value,
            )
        )
        task = result.scalars().first()
        if not task:
            return

        await self._mark_task_completed(task, patient_id, postgres_session)
        await self._update_challenge_progress(patient_id, task_type)
        await self._update_quest_progress(patient_id, task_type)

    async def _mark_task_completed(
        self,
        task: DailyTask,
        patient_id: UUID,
        session: AsyncSession,
    ) -> None:
        """Mark a task completed, grant XP, and evaluate achievements.

        Rolls back the task status if the XP grant fails so the task
        remains pending and can be retried.
        """
        task.status = TaskStatus.COMPLETED.value
        task.completed_at = datetime.now().replace(tzinfo=None)
        try:
            await self.xp_service.grant_xp(
                patient_id=patient_id,
                amount=task.xp_reward,
                source_type="task",
                source_id=task.task_id,
                description=f"Task: {task.title}",
            )
        except Exception:
            task.status = TaskStatus.PENDING.value
            task.completed_at = None
            await session.commit()
            raise
        await session.commit()
        await self.achievement_evaluator.evaluate_all(patient_id=patient_id)
        await self._try_process_streak(patient_id)

    async def _update_quest_progress(
        self, patient_id: UUID, task_type: str
    ) -> None:
        """Increment weekly quest progress based on completed task type."""
        from lib.models.gamification import WeeklyQuest

        quest_map = {
            "LOG_MEAL": "meals_5_of_7",
            "HIT_STEP_GOAL": "steps_5_of_7",
            "LOG_MOOD": "mood_7_of_7",
            "LOG_SLEEP": "sleep_7_of_7",
        }
        quest_type = quest_map.get(task_type)
        if not quest_type:
            return

        try:
            today = await self._patient_today(patient_id)
            week_start = today - timedelta(days=today.weekday())

            async with self.postgres_store.get_session() as session:
                result = await session.execute(
                    select(WeeklyQuest).where(
                        WeeklyQuest.patient_id == patient_id,
                        WeeklyQuest.week_start == week_start,
                        WeeklyQuest.quest_type == quest_type,
                        WeeklyQuest.status == "active",
                    )
                )
                quest = result.scalars().first()
                if not quest:
                    return

                quest.current_value += 1
                if quest.current_value >= quest.target_value:
                    quest.status = "completed"
                    quest.completed_at = datetime.now().replace(tzinfo=None)
                    await session.commit()
                    # Grant quest XP
                    await self.xp_service.grant_xp(
                        patient_id=patient_id,
                        amount=quest.xp_reward,
                        source_type="quest",
                        source_id=quest.quest_id,
                        description=f"Weekly quest: {quest.title}",
                        respect_cap=False,
                    )
                else:
                    await session.commit()
        except Exception:
            logger.opt(exception=True).debug(
                f"Quest progress update failed for {patient_id}"
            )

        # Check "all_tasks_3_days" quest: if all today's tasks are completed
        try:
            today = await self._patient_today(patient_id)
            week_start = today - timedelta(days=today.weekday())
            async with self.postgres_store.get_session() as session:
                all_tasks = await session.execute(
                    select(DailyTask).where(
                        DailyTask.patient_id == patient_id,
                        DailyTask.task_date == today,
                    )
                )
                tasks = all_tasks.scalars().all()
                if tasks and all(t.status == TaskStatus.COMPLETED.value for t in tasks):
                    # Count how many days this week already had all tasks completed
                    # to avoid double-counting the same day
                    from sqlalchemy import func as _func
                    perfect_days_result = await session.execute(
                        select(_func.count(_func.distinct(DailyTask.task_date))).where(
                            DailyTask.patient_id == patient_id,
                            DailyTask.task_date >= week_start,
                            DailyTask.task_date <= today,
                            DailyTask.status == TaskStatus.COMPLETED.value,
                        )
                    )
                    # This is an approximation — counts days with ANY completed task.
                    # The true count of "all completed" days is expensive to compute,
                    # so we use the quest's current_value as the guard instead:
                    quest_result = await session.execute(
                        select(WeeklyQuest).where(
                            WeeklyQuest.patient_id == patient_id,
                            WeeklyQuest.week_start == week_start,
                            WeeklyQuest.quest_type == "all_tasks_3_days",
                            WeeklyQuest.status == "active",
                        )
                    )
                    quest = quest_result.scalars().first()
                    if quest:
                        # Bulk query: fetch ALL tasks for this week, group by date in Python
                        week_tasks_result = await session.execute(
                            select(DailyTask).where(
                                DailyTask.patient_id == patient_id,
                                DailyTask.task_date >= week_start,
                                DailyTask.task_date <= today,
                            )
                        )
                        tasks_by_date: dict = {}
                        for t in week_tasks_result.scalars().all():
                            tasks_by_date.setdefault(t.task_date, []).append(t)
                        all_days = {
                            d for d, day_tasks in tasks_by_date.items()
                            if day_tasks and all(
                                t.status == TaskStatus.COMPLETED.value for t in day_tasks
                            )
                        }
                        new_value = float(len(all_days))
                        if new_value > quest.current_value:
                            quest.current_value = new_value
                        if quest.current_value >= quest.target_value:
                            quest.status = "completed"
                            quest.completed_at = datetime.now().replace(tzinfo=None)
                            await session.commit()
                            await self.xp_service.grant_xp(
                                patient_id=patient_id,
                                amount=quest.xp_reward,
                                source_type="quest",
                                source_id=quest.quest_id,
                                description=f"Weekly quest: {quest.title}",
                                respect_cap=False,
                            )
                        else:
                            await session.commit()
        except Exception:
            pass

    async def _update_challenge_progress(
        self, patient_id: UUID, task_type: str
    ) -> None:
        """Map completed task types to challenge metric types."""
        from lib.core.container import container
        from lib.services.gamification.challenge_service import ChallengeService

        metric_map = {
            "HIT_CALORIE_TARGET": "calorie_target_hits",
        }
        metric = metric_map.get(task_type)
        if not metric:
            return
        try:
            challenge_service = container.resolve(ChallengeService)
            await challenge_service.update_participant_progress(
                patient_id, metric, 1.0
            )
        except Exception:
            pass  # Fire-and-forget

    async def _increment_challenge_metric(
        self,
        patient_id: UUID,
        metric_type: str,
        increment: float,
    ) -> None:
        from lib.core.container import container
        from lib.services.gamification.challenge_service import ChallengeService

        try:
            challenge_service = container.resolve(ChallengeService)
            await challenge_service.update_participant_progress(
                patient_id=patient_id,
                metric_type=metric_type,
                increment=increment,
            )
        except Exception:
            pass

    @with_postgres_session
    async def _evaluate_step_goal(
        self,
        patient_id: UUID,
        steps: float,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        today = await self._patient_today(patient_id)
        result = await postgres_session.execute(
            select(DailyTask).where(
                DailyTask.patient_id == patient_id,
                DailyTask.task_date == today,
                DailyTask.task_type == TaskType.HIT_STEP_GOAL.value,
                DailyTask.status == TaskStatus.PENDING.value,
            )
        )
        task = result.scalars().first()
        if not task or not task.target_value:
            return

        previous_steps = float(task.current_value or 0)
        task.current_value = steps
        if steps > previous_steps:
            await self._increment_challenge_metric(
                patient_id,
                metric_type="steps",
                increment=steps - previous_steps,
            )
        from lib.schemas.gamification import STEP_GOAL_THRESHOLD_PCT
        if steps >= task.target_value * STEP_GOAL_THRESHOLD_PCT:
            await self._mark_task_completed(task, patient_id, postgres_session)
            await self._update_quest_progress(patient_id, TaskType.HIT_STEP_GOAL.value)
        else:
            await postgres_session.commit()

    @with_postgres_session
    async def _evaluate_range_target(
        self,
        patient_id: UUID,
        actual_value: float,
        task_type: TaskType,
        lower_pct: float,
        upper_pct: float,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        """Evaluate a range-based target task (calories, protein, etc.).

        Completes when actual_value >= lower bound. No upper cap — hitting
        136g protein on a 50g target is a success, not a failure.
        """
        today = await self._patient_today(patient_id)
        result = await postgres_session.execute(
            select(DailyTask).where(
                DailyTask.patient_id == patient_id,
                DailyTask.task_date == today,
                DailyTask.task_type == task_type.value,
                DailyTask.status == TaskStatus.PENDING.value,
            )
        )
        task = result.scalars().first()
        if not task or not task.target_value:
            return

        task.current_value = actual_value
        lower = task.target_value * lower_pct
        if actual_value >= lower:
            await self._mark_task_completed(task, patient_id, postgres_session)
            await self._update_challenge_progress(patient_id, task_type.value)
            await self._update_quest_progress(patient_id, task_type.value)
        else:
            await postgres_session.commit()

    async def _try_process_streak(self, patient_id: UUID) -> None:
        """Process streak immediately if patient meets the activity threshold today.

        Called after every task completion so the streak updates in real-time
        instead of waiting for the 2 AM nightly cron.
        """
        try:
            from lib.core.container import container
            from lib.services.gamification.streak_service import StreakService

            today = await self._patient_today(patient_id)
            streak_service = container.resolve(StreakService)
            await streak_service.process_streak(patient_id, today)
        except Exception:
            logger.opt(exception=True).debug(
                f"Real-time streak check failed for {patient_id}"
            )

    async def _refresh_macro_progress(self, patient_id: UUID) -> None:
        """Update progress and auto-complete calorie/protein tasks in real-time.

        Called on every meal log. Fetches current day totals and evaluates
        whether targets are met — same logic as the EOD evaluator but immediate.
        """
        try:
            from lib.core.container import container
            from lib.services.reports.meal.processor import MealStatsProcessor
            from lib.schemas.gamification import CALORIE_TOLERANCE_PCT, PROTEIN_TOLERANCE_PCT

            today = await self._patient_today(patient_id)
            meal_processor = container.resolve(MealStatsProcessor)
            daily_stats = await meal_processor.get_meal_report_by_date(str(patient_id), today)
            if not daily_stats:
                return

            total_cal = getattr(daily_stats, "calories", None)
            total_prot = getattr(daily_stats, "proteins", None)

            if total_cal is not None:
                await self._evaluate_range_target(
                    patient_id, total_cal,
                    TaskType.HIT_CALORIE_TARGET,
                    1 - CALORIE_TOLERANCE_PCT, 1 + CALORIE_TOLERANCE_PCT,
                )
            if total_prot is not None:
                await self._evaluate_range_target(
                    patient_id, total_prot,
                    TaskType.HIT_PROTEIN_TARGET,
                    1 - PROTEIN_TOLERANCE_PCT, 1 + PROTEIN_TOLERANCE_PCT,
                )
        except Exception:
            logger.opt(exception=True).debug(
                f"Macro progress refresh failed for {patient_id}"
            )

    async def _patient_today(self, patient_id: UUID) -> date:
        tz_name = await self._resolve_tz(patient_id)
        return local_today(tz_name)

    async def _resolve_tz(self, patient_id: UUID) -> str | None:
        if patient_id in self._tz_cache:
            return self._tz_cache[patient_id]
        from lib.services.gamification.time_utils import get_patient_timezone

        async with self.postgres_store.get_session() as session:
            tz_name = await get_patient_timezone(patient_id, session)
        self._tz_cache[patient_id] = tz_name
        return tz_name
