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

    async def _ensure_tasks_exist(self, patient_id: UUID) -> None:
        """Ensure daily tasks exist before trying to complete them."""
        from lib.services.gamification.task_generator import TaskGeneratorService
        from lib.core.container import container
        task_gen = container.resolve(TaskGeneratorService)
        await task_gen.generate_daily_tasks(patient_id, date.today())

    async def on_meal_logged(self, patient_id: UUID) -> None:
        try:
            await self._complete_task(patient_id, TaskType.LOG_MEAL.value)
        except Exception:
            logger.opt(exception=True).warning(
                f"Gamification hook on_meal_logged failed for {patient_id}"
            )

    async def on_sleep_logged(self, patient_id: UUID) -> None:
        try:
            await self._complete_task(patient_id, TaskType.LOG_SLEEP.value)
        except Exception:
            logger.opt(exception=True).warning(
                f"Gamification hook on_sleep_logged failed for {patient_id}"
            )

    async def on_mood_logged(self, patient_id: UUID) -> None:
        try:
            await self._complete_task(patient_id, TaskType.LOG_MOOD.value)
        except Exception:
            logger.opt(exception=True).warning(
                f"Gamification hook on_mood_logged failed for {patient_id}"
            )

    async def on_glucose_synced(self, patient_id: UUID) -> None:
        try:
            await self._complete_task(patient_id, TaskType.LOG_GLUCOSE.value)
        except Exception:
            logger.opt(exception=True).warning(
                f"Gamification hook on_glucose_synced failed for {patient_id}"
            )

    async def on_weight_logged(self, patient_id: UUID) -> None:
        try:
            await self._complete_task(patient_id, TaskType.LOG_WEIGHT.value)
        except Exception:
            logger.opt(exception=True).warning(
                f"Gamification hook on_weight_logged failed for {patient_id}"
            )

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
        try:
            if total_calories is not None:
                await self._evaluate_calorie_target(
                    patient_id, total_calories
                )
            if total_protein is not None:
                await self._evaluate_protein_target(
                    patient_id, total_protein
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
        today = date.today()

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

        now = datetime.now().replace(tzinfo=None)
        task.status = TaskStatus.COMPLETED.value
        task.completed_at = now

        await self.xp_service.grant_xp(
            patient_id=patient_id,
            amount=task.xp_reward,
            source_type="task",
            source_id=task.task_id,
            description=f"Task: {task.title}",
            postgres_session=postgres_session,
        )

        await postgres_session.commit()

        await self.achievement_evaluator.evaluate_all(patient_id=patient_id)

        # Update challenge progress based on task type
        await self._update_challenge_progress(patient_id, task_type)

        # Update weekly quest progress
        await self._update_quest_progress(patient_id, task_type)

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
            today = date.today()
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
            today = date.today()
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
                        quest.current_value += 1
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
            "LOG_MEAL": "meals_logged",
            "HIT_STEP_GOAL": "steps",
            "COMPLETE_WORKOUT": "workouts",
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

    @with_postgres_session
    async def _evaluate_step_goal(
        self,
        patient_id: UUID,
        steps: float,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        today = date.today()
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

        task.current_value = steps
        # 80% threshold
        if steps >= task.target_value * 0.8:
            task.status = TaskStatus.COMPLETED.value
            task.completed_at = datetime.now().replace(tzinfo=None)
            await self.xp_service.grant_xp(
                patient_id=patient_id,
                amount=task.xp_reward,
                source_type="task",
                source_id=task.task_id,
                description=f"Task: {task.title}",
                postgres_session=postgres_session,
            )
            await postgres_session.commit()
            await self.achievement_evaluator.evaluate_all(
                patient_id=patient_id
            )
            await self._update_challenge_progress(patient_id, TaskType.HIT_STEP_GOAL.value)
            await self._update_quest_progress(patient_id, TaskType.HIT_STEP_GOAL.value)
        else:
            await postgres_session.commit()

    @with_postgres_session
    async def _evaluate_calorie_target(
        self,
        patient_id: UUID,
        total_calories: float,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        today = date.today()
        result = await postgres_session.execute(
            select(DailyTask).where(
                DailyTask.patient_id == patient_id,
                DailyTask.task_date == today,
                DailyTask.task_type == TaskType.HIT_CALORIE_TARGET.value,
                DailyTask.status == TaskStatus.PENDING.value,
            )
        )
        task = result.scalars().first()
        if not task or not task.target_value:
            return

        task.current_value = total_calories
        # ±15% tolerance
        lower = task.target_value * 0.85
        upper = task.target_value * 1.15
        if lower <= total_calories <= upper:
            task.status = TaskStatus.COMPLETED.value
            task.completed_at = datetime.now().replace(tzinfo=None)
            await self.xp_service.grant_xp(
                patient_id=patient_id,
                amount=task.xp_reward,
                source_type="task",
                source_id=task.task_id,
                description=f"Task: {task.title}",
                postgres_session=postgres_session,
            )
            await postgres_session.commit()
            await self.achievement_evaluator.evaluate_all(
                patient_id=patient_id
            )
            await self._update_challenge_progress(patient_id, TaskType.HIT_CALORIE_TARGET.value)
            await self._update_quest_progress(patient_id, TaskType.HIT_CALORIE_TARGET.value)
        else:
            await postgres_session.commit()

    @with_postgres_session
    async def _evaluate_protein_target(
        self,
        patient_id: UUID,
        total_protein: float,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        today = date.today()
        result = await postgres_session.execute(
            select(DailyTask).where(
                DailyTask.patient_id == patient_id,
                DailyTask.task_date == today,
                DailyTask.task_type == TaskType.HIT_PROTEIN_TARGET.value,
                DailyTask.status == TaskStatus.PENDING.value,
            )
        )
        task = result.scalars().first()
        if not task or not task.target_value:
            return

        task.current_value = total_protein
        # ±10% tolerance
        lower = task.target_value * 0.9
        upper = task.target_value * 1.1
        if lower <= total_protein <= upper:
            task.status = TaskStatus.COMPLETED.value
            task.completed_at = datetime.now().replace(tzinfo=None)
            await self.xp_service.grant_xp(
                patient_id=patient_id,
                amount=task.xp_reward,
                source_type="task",
                source_id=task.task_id,
                description=f"Task: {task.title}",
                postgres_session=postgres_session,
            )
            await postgres_session.commit()
            await self.achievement_evaluator.evaluate_all(
                patient_id=patient_id
            )
            await self._update_challenge_progress(patient_id, TaskType.HIT_PROTEIN_TARGET.value)
            await self._update_quest_progress(patient_id, TaskType.HIT_PROTEIN_TARGET.value)
        else:
            await postgres_session.commit()
