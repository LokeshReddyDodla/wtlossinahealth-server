"""Sync weight from vitals/fitness upload to patient profile + Qdrant."""

from __future__ import annotations

import logging
from typing import cast

from sqlalchemy import update
from sqlalchemy.orm import selectinload, joinedload

from lib.core.container import container
from lib.core.postgres_store import PostgresStore
from lib.models.patient import Patient as PatientModel
from lib.models.patient_eating_habit import PatientEatingHabit as PatientEatingHabitModel
from lib.schemas.patient import CorePatientProfile
from lib.workers.tasks.profile.enqueue import enqueue_generate_profile_vector_async

logger = logging.getLogger(__name__)


async def sync_profile_weight(patient_id: str, weight_kg: float) -> None:
    """Update profile weight columns and re-embed the profile vector.

    Fire-and-forget from vital/fitness upload paths.
    """
    try:
        postgres_store = cast(PostgresStore, container.resolve(PostgresStore))
        async with postgres_store.get_session() as session:
            await session.execute(
                update(PatientModel)
                .where(PatientModel.patient_id == patient_id)
                .values(weight=weight_kg, weight_kg=weight_kg)
            )
            await session.commit()

        async with postgres_store.get_session() as session:
            from sqlalchemy import select

            stmt = (
                select(PatientModel)
                .where(PatientModel.patient_id == patient_id)
                .options(
                    selectinload(PatientModel.daily_activity),
                    selectinload(PatientModel.food_allergies),
                    selectinload(PatientModel.drug_allergies),
                    selectinload(PatientModel.alcohol_consumption),
                    selectinload(PatientModel.smoking_habit),
                    selectinload(PatientModel.sleep_habit),
                    joinedload(PatientModel.eating_habit).joinedload(
                        PatientEatingHabitModel.meal_timings
                    ),
                    joinedload(PatientModel.eating_habit).joinedload(
                        PatientEatingHabitModel.diet_preferences
                    ),
                    selectinload(PatientModel.diet_plans),
                    selectinload(PatientModel.fitness_plans),
                    selectinload(PatientModel.diabetic_history),
                    selectinload(PatientModel.reproductive_health),
                    selectinload(PatientModel.family_diabetic_histories),
                    selectinload(PatientModel.medical_histories),
                )
            )
            result = await session.execute(stmt)
            patient = result.unique().scalar_one_or_none()
            if not patient:
                return

            profile_data = CorePatientProfile.from_orm(patient).model_dump(mode="json")
            await enqueue_generate_profile_vector_async(patient_id, profile_data)

        logger.info(f"Synced profile weight to {weight_kg}kg for {patient_id}")
    except Exception:
        logger.exception(f"Failed to sync profile weight for {patient_id}")
