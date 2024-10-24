from datetime import date as datetime_date
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.models.patient_diet_plan import \
    PatientDietPlan as PatientDietPlanModel
from lib.models.patient_fitness_plan import \
    PatientFitnessPlan as PatientFitnessPlanModel
from lib.models.patient_plan import PatientPlan as PatientPlanModel
from lib.schemas.patient_diet_plan import PatientDietPlanCreate
from lib.schemas.patient_fitness_plan import PatientFitnessPlanCreate


class PatientPlanService:
    def __init__(self, postgres_session: AsyncSession):
        self.postgres_session = postgres_session

    async def fetch_patient_plans(self, patient_id: str):
        """Fetch all plans for a given patient."""
        try:
            stmt = select(PatientPlanModel).where(
                PatientPlanModel.patient_id == patient_id
            )
            stmt = stmt.options(
                selectinload(PatientPlanModel.diet_plan),
                selectinload(PatientPlanModel.fitness_plan),
            )
            result = await self.postgres_session.execute(stmt)
            patient_plans = result.scalars().all()
            if not patient_plans:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Patient plans not found.",
                )
            return patient_plans

        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    async def create_diet_plan(
        self, diet_plan_data: PatientDietPlanCreate
    ) -> PatientDietPlanModel:
        """Create a new diet plan."""
        try:
            diet_plan = PatientDietPlanModel(**diet_plan_data.model_dump())
            self.postgres_session.add(diet_plan)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(diet_plan)
            return diet_plan
        except IntegrityError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Integrity Error: {str(e)}",
            )

    async def create_fitness_plan(
        self, fitness_plan_data: PatientFitnessPlanCreate
    ) -> PatientFitnessPlanModel:
        """Create a new fitness plan."""
        try:
            fitness_plan = PatientFitnessPlanModel(
                **fitness_plan_data.model_dump()
            )
            self.postgres_session.add(fitness_plan)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(fitness_plan)

            return fitness_plan
        except IntegrityError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Integrity Error: {str(e)}",
            )

    async def assign_patient_plan(
        self,
        patient_id: str,
        diet_plan_id: Optional[str],
        fitness_plan_id: Optional[str],
        end_date: Optional[datetime] = None,
    ) -> PatientPlanModel:
        """Assign diet and/or fitness plans to a patient."""
        try:
            patient_plan = PatientPlanModel(
                patient_id=patient_id,
                diet_plan_id=diet_plan_id,
                fitness_plan_id=fitness_plan_id,
                start_date=datetime.now(),
                end_date=end_date,
            )
            self.postgres_session.add(patient_plan)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(patient_plan)

            return patient_plan
        except IntegrityError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Integrity Error: {str(e)}",
            )

    async def get_active_patient_plan(
        self, patient_id: str, query_date: datetime_date
    ) -> Optional[PatientPlanModel]:
        """Fetch the active patient plan based on the given date."""
        try:
            stmt = (
                select(PatientPlanModel)
                .options(
                    selectinload(PatientPlanModel.diet_plan),
                    selectinload(PatientPlanModel.fitness_plan),
                )
                .where(
                    PatientPlanModel.patient_id == patient_id,
                    and_(
                        PatientPlanModel.start_date <= query_date,
                        or_(
                            PatientPlanModel.end_date.is_(None),
                            PatientPlanModel.end_date >= query_date,
                        ),
                    ),
                )
            )

            result = await self.postgres_session.execute(stmt)
            active_plan = result.scalars().first()

            return active_plan
        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    async def delete_patient_plan(self, plan_id: str):
        """Delete a specific plan."""
        try:
            stmt = select(PatientPlanModel).where(
                PatientPlanModel.plan_id == plan_id
            )
            result = await self.postgres_session.execute(stmt)
            patient_plan = result.scalars().first()

            if not patient_plan:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Plan not found.",
                )

            await self.postgres_session.delete(patient_plan)
            await self.postgres_session.commit()

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )
