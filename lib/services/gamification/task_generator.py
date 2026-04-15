"""Rule-based daily task generation from active plans."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import Challenge, ChallengeParticipant, DailyTask, GroupMember, WeeklyQuest
from lib.models.patient_diet_plan import PatientDietPlan
from lib.models.patient_fitness_plan import PatientFitnessPlan
from lib.models.patient_diabetic_history import PatientDiabeticHistory
from lib.models.patient_medication import PatientMedication
from lib.models.patient_prescription import PatientPrescription
from lib.schemas.gamification import SourceType, TaskStatus, TaskType
from lib.utils.postgres_session_decorator import with_postgres_session

# Base XP rewards per task type
_XP_REWARDS = {
    TaskType.LOG_MEAL: 15,
    TaskType.HIT_CALORIE_TARGET: 30,
    TaskType.HIT_PROTEIN_TARGET: 25,
    TaskType.HIT_STEP_GOAL: 30,
    TaskType.COMPLETE_WORKOUT: 40,
    TaskType.LOG_SLEEP: 15,
    TaskType.LOG_MOOD: 10,
    TaskType.LOG_GLUCOSE: 10,
    TaskType.LOG_WEIGHT: 20,
    TaskType.TAKE_MEDICATION_MORNING: 15,
    TaskType.TAKE_MEDICATION_AFTERNOON: 15,
    TaskType.TAKE_MEDICATION_EVENING: 15,
    TaskType.TAKE_MEDICATION_NIGHT: 15,
    TaskType.FOLLOW_UP_APPOINTMENT: 20,
}

_WEEKDAY_NAMES = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]

# Weekly quest pool (rule-based, rotating)
_QUEST_POOL = [
    {
        "quest_type": "meals_5_of_7",
        "title": "Meal Tracker",
        "description": "Log meals on 5 of 7 days this week",
        "target_value": 5,
        "xp_reward": 100,
    },
    {
        "quest_type": "steps_5_of_7",
        "title": "Step Chaser",
        "description": "Hit your step goal 5 of 7 days this week",
        "target_value": 5,
        "xp_reward": 100,
    },
    {
        "quest_type": "mood_7_of_7",
        "title": "Mindful Week",
        "description": "Log your mood every day this week",
        "target_value": 7,
        "xp_reward": 75,
    },
    {
        "quest_type": "sleep_7_of_7",
        "title": "Sleep Scholar",
        "description": "Log your sleep every day this week",
        "target_value": 7,
        "xp_reward": 75,
    },
    {
        "quest_type": "all_tasks_3_days",
        "title": "Perfect Days",
        "description": "Complete all daily tasks on 3 days this week",
        "target_value": 3,
        "xp_reward": 150,
    },
]


class TaskGeneratorService:
    def __init__(self, postgres_store: PostgresStore) -> None:
        self.postgres_store = postgres_store

    @with_postgres_session
    async def generate_daily_tasks(
        self,
        patient_id: UUID,
        task_date: date,
        *,
        postgres_session: AsyncSession,
    ) -> List[DailyTask]:
        """Generate all daily tasks for a patient. Idempotent."""
        existing = await postgres_session.execute(
            select(DailyTask).where(
                DailyTask.patient_id == patient_id,
                DailyTask.task_date == task_date,
            )
        )
        existing_tasks = list(existing.scalars().all())
        existing_keys = {(task.task_type, task.source_id) for task in existing_tasks}

        tasks: List[DailyTask] = []

        # Check if patient is diabetic (has diabetic history record)
        is_diabetic = (
            await postgres_session.execute(
                select(PatientDiabeticHistory.patient_id).where(
                    PatientDiabeticHistory.patient_id == patient_id
                )
            )
        ).scalar_one_or_none() is not None

        # Habit tasks (always generated)
        tasks.extend(self._habit_tasks(patient_id, task_date, is_diabetic=is_diabetic))

        # Plan-derived tasks
        diet_tasks = await self._diet_plan_tasks(
            patient_id, task_date, postgres_session
        )
        tasks.extend(diet_tasks)

        fitness_tasks = await self._fitness_plan_tasks(
            patient_id, task_date, postgres_session
        )
        tasks.extend(fitness_tasks)

        challenge_tasks = await self._challenge_tasks(
            patient_id, task_date, postgres_session
        )
        tasks.extend(challenge_tasks)

        # Medication tasks
        medication_tasks = await self._medication_tasks(
            patient_id, task_date, postgres_session
        )
        tasks.extend(medication_tasks)

        # Follow-up appointment tasks
        follow_up_tasks = await self._follow_up_tasks(
            patient_id, task_date, postgres_session
        )
        tasks.extend(follow_up_tasks)

        for task in tasks:
            key = (task.task_type, task.source_id)
            if key in existing_keys:
                continue
            postgres_session.add(task)
            existing_tasks.append(task)
            existing_keys.add(key)

        try:
            await postgres_session.commit()
        except Exception:
            await postgres_session.rollback()
            # Re-fetch on conflict (concurrent generation)
            result = await postgres_session.execute(
                select(DailyTask).where(
                    DailyTask.patient_id == patient_id,
                    DailyTask.task_date == task_date,
                )
            )
            existing_tasks = list(result.scalars().all())
        return existing_tasks

    @with_postgres_session
    async def generate_weekly_quest(
        self,
        patient_id: UUID,
        week_start: date,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[WeeklyQuest]:
        """Generate a weekly quest for the given week. Idempotent."""
        existing = await postgres_session.execute(
            select(WeeklyQuest).where(
                WeeklyQuest.patient_id == patient_id,
                WeeklyQuest.week_start == week_start,
            )
        )
        if existing.scalars().first():
            return None

        # Pick quest based on week number (simple rotation)
        week_number = week_start.isocalendar()[1]
        quest_def = _QUEST_POOL[week_number % len(_QUEST_POOL)]

        quest = WeeklyQuest(
            patient_id=patient_id,
            week_start=week_start,
            quest_type=quest_def["quest_type"],
            title=quest_def["title"],
            description=quest_def["description"],
            target_value=quest_def["target_value"],
            xp_reward=quest_def["xp_reward"],
        )
        postgres_session.add(quest)
        await postgres_session.commit()
        await postgres_session.refresh(quest)
        return quest

    @with_postgres_session
    async def expire_old_tasks(
        self,
        patient_id: UUID,
        before_date: date,
        *,
        postgres_session: AsyncSession,
    ) -> int:
        """Mark all pending tasks before the given date as expired."""
        result = await postgres_session.execute(
            select(DailyTask).where(
                DailyTask.patient_id == patient_id,
                DailyTask.task_date < before_date,
                DailyTask.status == TaskStatus.PENDING.value,
            )
        )
        tasks = result.scalars().all()
        for task in tasks:
            task.status = TaskStatus.EXPIRED.value
        await postgres_session.commit()
        return len(tasks)

    def _habit_tasks(
        self, patient_id: UUID, task_date: date, *, is_diabetic: bool
    ) -> List[DailyTask]:
        habits = [
            (TaskType.LOG_MEAL, "Log your meals", "Track what you eat today"),
            (TaskType.LOG_SLEEP, "Log your sleep", "How did you sleep last night?"),
            (TaskType.LOG_MOOD, "Check in on your mood", "How are you feeling?"),
        ]

        if is_diabetic:
            habits.append(
                (TaskType.LOG_GLUCOSE, "Sync glucose data", "Keep your glucose data up to date")
            )

        # Weekly weight task only on Mondays
        if task_date.weekday() == 0:
            habits.append(
                (TaskType.LOG_WEIGHT, "Weekly weigh-in", "Step on the scale this week")
            )

        return [
            DailyTask(
                patient_id=patient_id,
                task_date=task_date,
                task_type=task_type.value,
                title=title,
                description=desc,
                source_type=SourceType.HABIT.value,
                xp_reward=_XP_REWARDS[task_type],
            )
            for task_type, title, desc in habits
        ]

    async def _diet_plan_tasks(
        self,
        patient_id: UUID,
        task_date: date,
        session: AsyncSession,
    ) -> List[DailyTask]:
        result = await session.execute(
            select(PatientDietPlan).where(
                PatientDietPlan.patient_id == patient_id,
                PatientDietPlan.status == "ACTIVE",
                PatientDietPlan.start_date <= task_date,
                or_(
                    PatientDietPlan.end_date.is_(None),
                    PatientDietPlan.end_date >= task_date,
                ),
            )
        )
        plan = result.scalars().first()
        if not plan:
            return []

        tasks = []
        if plan.calories:
            tasks.append(
                DailyTask(
                    patient_id=patient_id,
                    task_date=task_date,
                    task_type=TaskType.HIT_CALORIE_TARGET.value,
                    title=f"Stay within {int(plan.calories)} cal",
                    description=f"Hit your calorie target (±15%): {int(plan.calories)} kcal",
                    source_type=SourceType.DIET_PLAN.value,
                    source_id=plan.diet_plan_id,
                    target_value=plan.calories,
                    xp_reward=_XP_REWARDS[TaskType.HIT_CALORIE_TARGET],
                )
            )
        if plan.protein:
            tasks.append(
                DailyTask(
                    patient_id=patient_id,
                    task_date=task_date,
                    task_type=TaskType.HIT_PROTEIN_TARGET.value,
                    title=f"Get {int(plan.protein)}g+ protein",
                    description=f"Hit your protein target (±10%): {int(plan.protein)}g",
                    source_type=SourceType.DIET_PLAN.value,
                    source_id=plan.diet_plan_id,
                    target_value=plan.protein,
                    xp_reward=_XP_REWARDS[TaskType.HIT_PROTEIN_TARGET],
                )
            )
        return tasks

    async def _challenge_tasks(
        self,
        patient_id: UUID,
        task_date: date,
        session: AsyncSession,
    ) -> List[DailyTask]:
        """Generate informational tasks for active challenges.

        NOTE: Challenge tasks use a synthetic task_type (CHALLENGE_TASK_{id}).
        They are display-only — they do NOT count toward streak activity or earn
        XP directly. The xp_reward shown is the challenge's actual reward so the
        patient knows what they'll earn; it is only granted via
        challenge_service.finalize_challenge when the challenge ends.
        """
        result = await session.execute(
            select(ChallengeParticipant, Challenge)
            .join(Challenge)
            .where(
                Challenge.is_active == True,
                Challenge.start_date <= task_date,
                Challenge.end_date >= task_date,
                ChallengeParticipant.status == "active",
                (
                    (
                        (ChallengeParticipant.participant_type == "patient")
                        & (ChallengeParticipant.participant_id == patient_id)
                    )
                ),
            )
        )
        rows = list(result.all())

        from lib.services.gamification.queries import active_group_ids
        group_ids = await active_group_ids(patient_id, session)
        if group_ids:
            # Exclude challenges the patient individually withdrew from
            withdrawn_ids = (
                select(ChallengeParticipant.challenge_id).where(
                    ChallengeParticipant.participant_id == patient_id,
                    ChallengeParticipant.participant_type == "patient",
                    ChallengeParticipant.status == "withdrawn",
                )
            ).scalar_subquery()

            group_rows = await session.execute(
                select(ChallengeParticipant, Challenge)
                .join(Challenge)
                .where(
                    Challenge.is_active == True,
                    Challenge.start_date <= task_date,
                    Challenge.end_date >= task_date,
                    ChallengeParticipant.status == "active",
                    ChallengeParticipant.participant_type == "group",
                    ChallengeParticipant.participant_id.in_(group_ids),
                    Challenge.challenge_id.notin_(withdrawn_ids),
                )
            )
            rows.extend(group_rows.all())

        tasks: List[DailyTask] = []
        seen_challenges: set[UUID] = set()
        for row in rows:
            challenge = row.Challenge
            participant = row.ChallengeParticipant
            if challenge.challenge_id in seen_challenges:
                continue
            seen_challenges.add(challenge.challenge_id)
            participant_name = "your team" if participant.participant_type == "group" else "you"
            tasks.append(
                DailyTask(
                    patient_id=patient_id,
                    task_date=task_date,
                    task_type=f"{TaskType.CHALLENGE_TASK.value}_{challenge.challenge_id.hex}",
                    title=f"Challenge: {challenge.title}",
                    description=(
                        f"Help {participant_name} progress in this {challenge.scope.replace('_', ' ')} challenge."
                    ),
                    source_type=SourceType.CHALLENGE.value,
                    source_id=challenge.challenge_id,
                    target_value=challenge.target_value,
                    current_value=participant.current_value,
                    # Show the actual challenge XP reward so the patient knows
                    # what they'll earn on completion. XP is still only granted
                    # when the challenge ends via challenge_service.finalize_challenge.
                    xp_reward=challenge.xp_reward,
                )
            )

        return tasks

    async def _fitness_plan_tasks(
        self,
        patient_id: UUID,
        task_date: date,
        session: AsyncSession,
    ) -> List[DailyTask]:
        result = await session.execute(
            select(PatientFitnessPlan).where(
                PatientFitnessPlan.patient_id == patient_id,
                PatientFitnessPlan.status == "ACTIVE",
                PatientFitnessPlan.start_date <= task_date,
                or_(
                    PatientFitnessPlan.end_date.is_(None),
                    PatientFitnessPlan.end_date >= task_date,
                ),
            )
        )
        plan = result.scalars().first()
        if not plan:
            return []

        tasks = []

        # Steps goal
        if plan.steps_goal:
            tasks.append(
                DailyTask(
                    patient_id=patient_id,
                    task_date=task_date,
                    task_type=TaskType.HIT_STEP_GOAL.value,
                    title=f"Walk {int(plan.steps_goal)} steps",
                    description=f"Hit your step goal (80%+): {int(plan.steps_goal)} steps",
                    source_type=SourceType.FITNESS_PLAN.value,
                    source_id=plan.fitness_plan_id,
                    target_value=plan.steps_goal,
                    xp_reward=_XP_REWARDS[TaskType.HIT_STEP_GOAL],
                )
            )

        # Workout session for today
        content = plan.content or {}
        sessions = content.get("weekly_sessions") or []
        today_name = _WEEKDAY_NAMES[task_date.weekday()]
        for workout_session in sessions:
            if (workout_session.get("day") or "").lower() == today_name:
                session_type = workout_session.get("type", "workout")
                duration = workout_session.get("duration_min", 30)
                tasks.append(
                    DailyTask(
                        patient_id=patient_id,
                        task_date=task_date,
                        task_type=TaskType.COMPLETE_WORKOUT.value,
                        title=f"{session_type.title()} session ({duration} min)",
                        description=f"Complete your planned {session_type} workout",
                        source_type=SourceType.FITNESS_PLAN.value,
                        source_id=plan.fitness_plan_id,
                        target_value=duration,
                        xp_reward=_XP_REWARDS[TaskType.COMPLETE_WORKOUT],
                    )
                )
                break  # One workout task per day

        return tasks

    @staticmethod
    def _is_medication_due(med: PatientMedication, task_date: date) -> bool:
        """Check if a medication is due on a specific date based on its schedule."""
        schedule = med.schedule
        if not schedule:
            return True  # null schedule = daily (all 7 days)

        stype = schedule.get("type", "weekly")
        if stype == "weekly":
            days = schedule.get("days_of_week", [0, 1, 2, 3, 4, 5, 6])
            return task_date.weekday() in days
        elif stype == "interval":
            anchor_str = schedule.get("interval_anchor")
            interval = schedule.get("interval_days")
            if not anchor_str or not interval:
                return True  # malformed → safe default
            anchor = date.fromisoformat(str(anchor_str))
            return (task_date - anchor).days % interval == 0

        return True  # unknown type = daily

    async def _medication_tasks(
        self,
        patient_id: UUID,
        task_date: date,
        session: AsyncSession,
    ) -> List[DailyTask]:
        """Generate TAKE_MEDICATION_{SLOT} tasks from active medications."""
        result = await session.execute(
            select(PatientMedication).where(
                PatientMedication.patient_id == patient_id,
                PatientMedication.status == "active",
                PatientMedication.start_date <= task_date,
                or_(
                    PatientMedication.end_date.is_(None),
                    PatientMedication.end_date >= task_date,
                ),
            )
        )
        medications = result.scalars().all()
        if not medications:
            return []

        # Filter by schedule — skip meds not due on this day
        due_meds = [m for m in medications if self._is_medication_due(m, task_date)]
        if not due_meds:
            return []

        # Group medications by dose slot
        slot_meds: dict[str, list[PatientMedication]] = {}
        for med in due_meds:
            for dose in (med.doses or []):
                slot = dose.get("slot", "morning")
                slot_meds.setdefault(slot, []).append(med)

        slot_to_task_type = {
            "morning": TaskType.TAKE_MEDICATION_MORNING,
            "afternoon": TaskType.TAKE_MEDICATION_AFTERNOON,
            "evening": TaskType.TAKE_MEDICATION_EVENING,
            "night": TaskType.TAKE_MEDICATION_NIGHT,
        }

        tasks: List[DailyTask] = []
        for slot, meds in slot_meds.items():
            task_type = slot_to_task_type.get(slot)
            if not task_type:
                continue

            med_names = []
            for m in meds:
                name = f"{m.name} {m.strength}" if m.strength else m.name
                schedule = m.schedule
                if schedule:
                    stype = schedule.get("type", "weekly")
                    if stype == "weekly":
                        days = schedule.get("days_of_week", [0,1,2,3,4,5,6])
                        if len(days) < 7:
                            name += " (weekly)" if len(days) <= 2 else f" ({len(days)}x/week)"
                    elif stype == "interval":
                        interval = schedule.get("interval_days")
                        if interval == 2:
                            name += " (alternate days)"
                        elif interval:
                            name += f" (every {interval} days)"
                med_names.append(name)
            description = ", ".join(med_names)

            tasks.append(
                DailyTask(
                    patient_id=patient_id,
                    task_date=task_date,
                    task_type=task_type.value,
                    title=f"Take your {slot} medications",
                    description=description,
                    source_type=SourceType.MEDICATION.value,
                    xp_reward=_XP_REWARDS[task_type],
                )
            )

        return tasks

    async def _follow_up_tasks(
        self,
        patient_id: UUID,
        task_date: date,
        session: AsyncSession,
    ) -> List[DailyTask]:
        """Generate FOLLOW_UP_APPOINTMENT task on follow-up dates."""
        result = await session.execute(
            select(PatientPrescription).where(
                PatientPrescription.patient_id == patient_id,
                PatientPrescription.status == "confirmed",
                PatientPrescription.follow_up_required.is_(True),
                PatientPrescription.follow_up_date == task_date,
            )
        )
        prescriptions = result.scalars().all()
        if not prescriptions:
            return []

        tasks: List[DailyTask] = []
        for rx in prescriptions:
            doctor = rx.doctor_name or "your doctor"
            tasks.append(
                DailyTask(
                    patient_id=patient_id,
                    task_date=task_date,
                    task_type=TaskType.FOLLOW_UP_APPOINTMENT.value,
                    title=f"Follow up with {doctor}",
                    description="You have a scheduled follow-up appointment today",
                    source_type=SourceType.PRESCRIPTION.value,
                    source_id=rx.prescription_id,
                    xp_reward=_XP_REWARDS[TaskType.FOLLOW_UP_APPOINTMENT],
                )
            )

        return tasks
