"""Patient workout service — CRUD over manually-logged workout sessions.

Session flow (create):
  1. Normalize input to segments (backward compat: flat type+exercises → single segment).
  2. Validate every exercise_id exists in the catalog.
  3. Denormalize exercise_name from catalog into each line item.
  4. Insert PatientWorkout + segments + exercises + sets in one transaction.
  5. Fire-and-forget: enqueue Qdrant vector generation.
  6. Fire-and-forget: gamification hook (on_fitness_synced workout_completed=True).
"""

from __future__ import annotations

import logging
from datetime import date as date_type, datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lib.core.postgres_store import PostgresStore
from lib.models.exercise import Exercise
from lib.models.patient_workout import (
    PatientWorkout,
    PatientWorkoutExercise,
    PatientWorkoutSegment,
    PatientWorkoutSet,
)
from lib.schemas.patient_workout import (
    PatientWorkoutCreate,
    PatientWorkoutExerciseInput,
    PatientWorkoutExerciseResponse,
    PatientWorkoutListResponse,
    PatientWorkoutResponse,
    PatientWorkoutSegmentResponse,
    PatientWorkoutUpdate,
    WorkoutSetResponse,
)
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session

logger = logging.getLogger(__name__)

_EAGER_LOAD = (
    selectinload(PatientWorkout.segments)
    .selectinload(PatientWorkoutSegment.exercises)
    .selectinload(PatientWorkoutExercise.set_details)
)


class PatientWorkoutService:
    def __init__(self, postgres_store: PostgresStore):
        self.postgres_store = postgres_store

    # ── Response builders ────────────────────────────────────────────────

    @staticmethod
    def _set_to_response(row: PatientWorkoutSet) -> WorkoutSetResponse:
        return WorkoutSetResponse(
            id=row.id,
            set_number=row.set_number,
            reps=row.reps,
            weight_kg=row.weight_kg,
            duration_seconds=row.duration_seconds,
            distance_m=row.distance_m,
        )

    @staticmethod
    def _exercise_to_response(row: PatientWorkoutExercise) -> PatientWorkoutExerciseResponse:
        return PatientWorkoutExerciseResponse(
            id=row.id,
            exercise_id=row.exercise_id,
            exercise_name=row.exercise_name,
            order_index=row.order_index,
            sets=row.sets,
            reps=row.reps,
            weight_kg=row.weight_kg,
            duration_seconds=row.duration_seconds,
            distance_m=row.distance_m,
            notes=row.notes,
            set_details=[
                PatientWorkoutService._set_to_response(s)
                for s in (row.set_details or [])
            ],
        )

    @staticmethod
    def _segment_to_response(row: PatientWorkoutSegment) -> PatientWorkoutSegmentResponse:
        return PatientWorkoutSegmentResponse(
            id=row.id,
            type=row.type,
            duration_minutes=row.duration_minutes,
            order_index=row.order_index,
            exercises=[
                PatientWorkoutService._exercise_to_response(ex)
                for ex in (row.exercises or [])
            ],
        )

    @staticmethod
    def _build_set_rows(ex: PatientWorkoutExerciseInput) -> list[PatientWorkoutSet]:
        if ex.set_details:
            return [
                PatientWorkoutSet(
                    set_number=s.set_number,
                    reps=s.reps,
                    weight_kg=s.weight_kg,
                    duration_seconds=s.duration_seconds,
                    distance_m=s.distance_m,
                )
                for s in ex.set_details
            ]
        if ex.sets and ex.sets > 0:
            return [
                PatientWorkoutSet(
                    set_number=i + 1,
                    reps=ex.reps,
                    weight_kg=ex.weight_kg,
                    duration_seconds=ex.duration_seconds,
                    distance_m=ex.distance_m,
                )
                for i in range(ex.sets)
            ]
        return []

    @classmethod
    def _to_response(cls, row: PatientWorkout) -> PatientWorkoutResponse:
        segments = [cls._segment_to_response(seg) for seg in (row.segments or [])]

        all_exercises: list[PatientWorkoutExerciseResponse] = []
        for seg in segments:
            all_exercises.extend(seg.exercises)

        seg_types = sorted({seg.type for seg in segments})
        derived_type = seg_types[0] if len(seg_types) == 1 else (" + ".join(seg_types) if seg_types else "other")

        durations = [seg.duration_minutes for seg in segments if seg.duration_minutes is not None]
        derived_duration = sum(durations) if durations else None

        return PatientWorkoutResponse(
            id=row.id,
            patient_id=row.patient_id,
            date=row.date,
            time=row.time,
            type=derived_type,
            duration_minutes=derived_duration,
            intensity=row.intensity,
            calories_burned=row.calories_burned,
            notes=row.notes,
            image_url=row.image_url,
            source=row.source,
            fitness_plan_session_id=row.fitness_plan_session_id,
            uploaded_at=row.uploaded_at or datetime.now().replace(tzinfo=None),
            segments=segments,
            exercises=all_exercises,
        )

    # ── Catalog validation ───────────────────────────────────────────────

    async def _validate_catalog_ids(
        self,
        exercises: list[PatientWorkoutExerciseInput],
        postgres_session: AsyncSession,
    ) -> dict[str, str]:
        """Return {exercise_id: exercise_name} for all referenced catalog entries.
        Raises 404 if any id is missing."""
        if not exercises:
            return {}
        ids = list({ex.exercise_id for ex in exercises})
        result = await postgres_session.execute(
            select(Exercise.id, Exercise.name).where(Exercise.id.in_(ids))
        )
        found = {row.id: row.name for row in result.all()}
        missing = [eid for eid in ids if eid not in found]
        if missing:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Unknown exercise_id(s) in request",
                detail=", ".join(missing),
            )
        return found

    # ── Create ───────────────────────────────────────────────────────────

    @with_postgres_session
    async def create(
        self,
        patient_id: str,
        data: PatientWorkoutCreate,
        *,
        postgres_session: AsyncSession,
    ) -> PatientWorkoutResponse:
        all_exercises = [ex for seg in data.segments for ex in seg.exercises]
        catalog_names = await self._validate_catalog_ids(all_exercises, postgres_session)

        try:
            workout = PatientWorkout(
                patient_id=patient_id,
                date=data.date,
                time=data.time,
                intensity=data.intensity,
                calories_burned=data.calories_burned,
                notes=data.notes,
                image_url=data.image_url,
                source=data.source,
                fitness_plan_session_id=data.fitness_plan_session_id,
            )
            for seg_input in data.segments:
                segment = PatientWorkoutSegment(
                    type=seg_input.type,
                    duration_minutes=seg_input.duration_minutes,
                    order_index=seg_input.order_index,
                )
                for ex in seg_input.exercises:
                    exercise_row = PatientWorkoutExercise(
                        exercise_id=ex.exercise_id,
                        exercise_name=catalog_names[ex.exercise_id],
                        order_index=ex.order_index,
                        sets=ex.sets if ex.sets else (len(ex.set_details) if ex.set_details else None),
                        reps=ex.reps,
                        weight_kg=ex.weight_kg,
                        duration_seconds=ex.duration_seconds,
                        distance_m=ex.distance_m,
                        notes=ex.notes,
                    )
                    exercise_row.set_details = self._build_set_rows(ex)
                    segment.exercises.append(exercise_row)
                workout.segments.append(segment)

            postgres_session.add(workout)
            await postgres_session.commit()
            workout = (
                await postgres_session.execute(
                    select(PatientWorkout)
                    .where(PatientWorkout.id == workout.id)
                    .options(_EAGER_LOAD)
                )
            ).scalar_one()
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

        response = self._to_response(workout)
        await self._fire_vector(patient_id, response)
        await self._fire_report_regeneration(patient_id, workout.date)
        await self._fire_gamification(patient_id)
        return response

    # ── Get / List ───────────────────────────────────────────────────────

    @with_postgres_session
    async def get(
        self,
        patient_id: str,
        workout_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[PatientWorkoutResponse]:
        row = (
            await postgres_session.execute(
                select(PatientWorkout)
                .where(
                    PatientWorkout.id == UUID(workout_id),
                    PatientWorkout.patient_id == UUID(patient_id),
                )
                .options(_EAGER_LOAD)
            )
        ).scalar_one_or_none()
        return self._to_response(row) if row else None

    @with_postgres_session
    async def list(
        self,
        patient_id: str,
        *,
        start_date: Optional[date_type] = None,
        end_date: Optional[date_type] = None,
        limit: int = 20,
        offset: int = 0,
        postgres_session: AsyncSession,
    ) -> PatientWorkoutListResponse:
        if not end_date:
            end_date = date_type.today() + timedelta(days=1)
        if not start_date:
            start_date = end_date - timedelta(days=30)

        from sqlalchemy import func

        base = select(PatientWorkout).where(
            PatientWorkout.patient_id == UUID(patient_id),
            PatientWorkout.date >= start_date,
            PatientWorkout.date <= end_date,
        )
        total = (
            await postgres_session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()

        rows = (
            await postgres_session.execute(
                base.options(_EAGER_LOAD)
                .order_by(PatientWorkout.date.desc(), PatientWorkout.time.desc().nulls_last())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()

        return PatientWorkoutListResponse(
            total=total,
            limit=limit,
            offset=offset,
            items=[self._to_response(r) for r in rows],
        )

    # ── Update / Delete ──────────────────────────────────────────────────

    @with_postgres_session
    async def update(
        self,
        patient_id: str,
        workout_id: str,
        data: PatientWorkoutUpdate,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[PatientWorkoutResponse]:
        row = (
            await postgres_session.execute(
                select(PatientWorkout)
                .where(
                    PatientWorkout.id == UUID(workout_id),
                    PatientWorkout.patient_id == UUID(patient_id),
                )
                .options(_EAGER_LOAD)
            )
        ).scalar_one_or_none()
        if not row:
            return None

        for field in (
            "date", "time", "intensity",
            "calories_burned", "notes", "image_url", "fitness_plan_session_id",
        ):
            value = getattr(data, field)
            if value is not None:
                setattr(row, field, value)

        if data.segments is not None:
            all_exercises = [ex for seg in data.segments for ex in seg.exercises]
            catalog_names = await self._validate_catalog_ids(
                all_exercises, postgres_session
            )
            for existing_seg in list(row.segments):
                await postgres_session.delete(existing_seg)
            await postgres_session.flush()

            for seg_input in data.segments:
                segment = PatientWorkoutSegment(
                    type=seg_input.type,
                    duration_minutes=seg_input.duration_minutes,
                    order_index=seg_input.order_index,
                )
                for ex in seg_input.exercises:
                    exercise_row = PatientWorkoutExercise(
                        exercise_id=ex.exercise_id,
                        exercise_name=catalog_names[ex.exercise_id],
                        order_index=ex.order_index,
                        sets=ex.sets if ex.sets else (len(ex.set_details) if ex.set_details else None),
                        reps=ex.reps,
                        weight_kg=ex.weight_kg,
                        duration_seconds=ex.duration_seconds,
                        distance_m=ex.distance_m,
                        notes=ex.notes,
                    )
                    exercise_row.set_details = self._build_set_rows(ex)
                    segment.exercises.append(exercise_row)
                row.segments.append(segment)

        await postgres_session.commit()
        row = (
            await postgres_session.execute(
                select(PatientWorkout)
                .where(PatientWorkout.id == row.id)
                .options(_EAGER_LOAD)
            )
        ).scalar_one()

        response = self._to_response(row)
        await self._fire_vector(patient_id, response)
        await self._fire_report_regeneration(patient_id, row.date)
        return response

    @with_postgres_session
    async def delete(
        self,
        patient_id: str,
        workout_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> bool:
        row = (
            await postgres_session.execute(
                select(PatientWorkout).where(
                    PatientWorkout.id == UUID(workout_id),
                    PatientWorkout.patient_id == UUID(patient_id),
                )
            )
        ).scalar_one_or_none()
        if not row:
            return False
        workout_date = row.date
        await postgres_session.delete(row)
        await postgres_session.commit()

        try:
            from lib.core.container import container
            from lib.services.vector import WorkoutVectorService
            vector_service = container.resolve(WorkoutVectorService)
            await vector_service.delete_workout_vector(workout_id)
        except Exception as e:
            logger.warning(f"Failed to delete workout vector {workout_id}: {e}")

        await self._fire_report_regeneration(patient_id, workout_date)
        return True

    # ── Side effects (fire-and-forget) ───────────────────────────────────

    @staticmethod
    async def _fire_vector(patient_id: str, workout: PatientWorkoutResponse) -> None:
        try:
            from lib.workers.tasks.workout.enqueue import (
                enqueue_generate_workout_vector_async,
            )
            payload = workout.model_dump(mode="json")
            await enqueue_generate_workout_vector_async(
                patient_id=str(patient_id),
                workout_id=str(workout.id),
                workout_data=payload,
            )
        except Exception as e:
            logger.warning(f"Failed to enqueue workout vector: {e}")

    @staticmethod
    async def _fire_report_regeneration(patient_id: str, workout_date) -> None:
        """Enqueue fitness report regeneration so MongoDB reports include this workout."""
        try:
            from datetime import datetime, time
            from lib.workers.tasks.fitness.enqueue import (
                enqueue_process_fitness_upload_async,
            )
            start_dt = datetime.combine(workout_date, time.min)
            end_dt = datetime.combine(workout_date, time.max)
            await enqueue_process_fitness_upload_async(
                patient_id=str(patient_id),
                start_date=start_dt,
                end_date=end_dt,
            )
        except Exception as e:
            logger.warning(f"Failed to enqueue report regeneration: {e}")

    @staticmethod
    async def _fire_gamification(patient_id: str) -> None:
        try:
            from lib.core.container import container
            from lib.services.gamification.event_handler import (
                GamificationEventHandler,
            )

            handler = container.resolve(GamificationEventHandler)
            await handler.on_fitness_synced(
                patient_id=UUID(patient_id),
                workout_completed=True,
            )
        except Exception as e:
            logger.warning(f"Failed to fire gamification hook: {e}")
