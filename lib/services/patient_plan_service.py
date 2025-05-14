from datetime import date as datetime_date
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.core.postgres_store import PostgresStore
from lib.models.patient_diet_plan import (
    PatientDietPlan as PatientDietPlanModel,
)
from lib.models.patient_fitness_plan import (
    PatientFitnessPlan as PatientFitnessPlanModel,
)
from lib.models.patient_plan import PatientPlan as PatientPlanModel
from lib.schemas.patient_diet_plan import PatientDietPlanCreate
from lib.schemas.patient_fitness_plan import PatientFitnessPlanCreate
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session


class PatientPlanService:
    def __init__(
        self,
        postgres_store: PostgresStore,
    ):
        self.postgres_store = postgres_store

    @with_postgres_session
    async def fetch_patient_plans(
        self, patient_id: str, *, postgres_session: AsyncSession
    ):
        try:
            stmt = (
                select(PatientPlanModel)
                .where(PatientPlanModel.patient_id == patient_id)
                .options(
                    selectinload(PatientPlanModel.diet_plan),
                    selectinload(PatientPlanModel.fitness_plan),
                )
            )

            result = await postgres_session.execute(stmt)
            patient_plans = result.scalars().all()
            if not patient_plans:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=f"No plans found for patient with ID '{patient_id}'.",
                )
            return patient_plans

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch patient plans.",
                detail=str(e),
            )

    @with_postgres_session
    async def create_diet_plan(
        self,
        diet_plan_data: PatientDietPlanCreate,
        *,
        postgres_session: AsyncSession,
    ) -> PatientDietPlanModel:
        try:
            diet_plan = PatientDietPlanModel(**diet_plan_data.model_dump())
            postgres_session.add(diet_plan)
            await postgres_session.commit()
            await postgres_session.refresh(diet_plan)
            return diet_plan
        except IntegrityError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Failed to create diet plan due to an integrity error.",
                detail=str(e),
            )

    @with_postgres_session
    async def create_fitness_plan(
        self,
        fitness_plan_data: PatientFitnessPlanCreate,
        *,
        postgres_session: AsyncSession,
    ) -> PatientFitnessPlanModel:
        try:
            fitness_plan = PatientFitnessPlanModel(
                **fitness_plan_data.model_dump()
            )
            postgres_session.add(fitness_plan)
            await postgres_session.commit()
            await postgres_session.refresh(fitness_plan)

            return fitness_plan
        except IntegrityError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Failed to create fitness plan due to an integrity error.",
                detail=str(e),
            )

    @with_postgres_session
    async def assign_patient_plan(
        self,
        patient_id: str,
        diet_plan_id: Optional[str],
        fitness_plan_id: Optional[str],
        end_date: Optional[datetime] = None,
        *,
        postgres_session: AsyncSession,
    ) -> PatientPlanModel:
        try:
            patient_plan = PatientPlanModel(
                patient_id=patient_id,
                diet_plan_id=diet_plan_id,
                fitness_plan_id=fitness_plan_id,
                start_date=datetime.now(),
                end_date=end_date,
            )
            postgres_session.add(patient_plan)
            await postgres_session.commit()
            await postgres_session.refresh(patient_plan)

            return patient_plan
        except IntegrityError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Failed to assign patient plan due to an integrity error.",
                detail=str(e),
            )

    @with_postgres_session
    async def get_active_patient_plan(
        self,
        patient_id: str,
        query_date: datetime_date,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[PatientPlanModel]:
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

            result = await postgres_session.execute(stmt)
            active_plan = result.scalars().first()

            return active_plan
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch active patient plan.",
                detail=str(e),
            )

    @with_postgres_session
    async def delete_patient_plan(
        self, plan_id: str, *, postgres_session: AsyncSession
    ):
        try:
            stmt = select(PatientPlanModel).where(
                PatientPlanModel.plan_id == plan_id
            )
            result = await postgres_session.execute(stmt)
            patient_plan = result.scalars().first()

            if not patient_plan:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=f"Patient plan with ID '{plan_id}' not found.",
                )

            await postgres_session.delete(patient_plan)
            await postgres_session.commit()

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=f"Failed to delete patient plan with ID '{plan_id}'.",
                detail=str(e),
            )
