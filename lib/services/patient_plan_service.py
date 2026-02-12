from datetime import date as datetime_date
from datetime import datetime
from typing import Optional, List

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

    # ==================== DIET PLAN METHODS ====================

    @with_postgres_session
    async def create_diet_plan(
        self,
        patient_id: str,
        diet_plan_data: PatientDietPlanCreate,
        start_date: datetime_date,
        end_date: Optional[datetime_date] = None,
        is_default: bool = False,
        status: str = "ACTIVE",
        plan_reason: Optional[str] = None,
        *,
        postgres_session: AsyncSession,
    ) -> PatientDietPlanModel:
        """Create a new diet plan for a patient with date range and lifecycle fields."""
        try:
            # Check if trying to set is_default when another default exists
            if is_default:
                existing_default = await self.get_default_diet_plan(
                    patient_id, postgres_session=postgres_session
                )
                if existing_default:
                    raise_http_exception(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message=f"Patient {patient_id} already has a default diet plan.",
                    )

            diet_plan = PatientDietPlanModel(
                patient_id=patient_id,
                start_date=start_date,
                end_date=end_date,
                is_default=is_default,
                status=status,
                plan_reason=plan_reason,
                **diet_plan_data.model_dump(),
            )
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
    async def get_active_diet_plan(
        self,
        patient_id: str,
        query_date: Optional[datetime_date] = None,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[PatientDietPlanModel]:
        """Get the active diet plan for a patient on a specific date."""
        try:
            if query_date is None:
                query_date = datetime.now().date()

            stmt = (
                select(PatientDietPlanModel)
                .where(
                    PatientDietPlanModel.patient_id == patient_id,
                    PatientDietPlanModel.status == "ACTIVE",
                    PatientDietPlanModel.start_date <= query_date,
                    or_(
                        PatientDietPlanModel.end_date.is_(None),
                        PatientDietPlanModel.end_date >= query_date,
                    ),
                )
                .order_by(PatientDietPlanModel.updated_at.desc())
            )

            result = await postgres_session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch active diet plan.",
                detail=str(e),
            )

    @with_postgres_session
    async def get_default_diet_plan(
        self,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[PatientDietPlanModel]:
        """Get the default diet plan for a patient (set during onboarding)."""
        try:
            stmt = (
                select(PatientDietPlanModel)
                .where(
                    PatientDietPlanModel.patient_id == patient_id,
                    PatientDietPlanModel.is_default.is_(True),
                    PatientDietPlanModel.status == "ACTIVE",
                )
            )

            result = await postgres_session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch default diet plan.",
                detail=str(e),
            )

    @with_postgres_session
    async def get_patient_diet_plans(
        self,
        patient_id: str,
        status_filter: Optional[str] = None,
        *,
        postgres_session: AsyncSession,
    ) -> List[PatientDietPlanModel]:
        """Get all diet plans for a patient, optionally filtered by status."""
        try:
            stmt = select(PatientDietPlanModel).where(
                PatientDietPlanModel.patient_id == patient_id
            )

            if status_filter:
                stmt = stmt.where(PatientDietPlanModel.status == status_filter)

            stmt = stmt.order_by(PatientDietPlanModel.start_date.desc())

            result = await postgres_session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch patient diet plans.",
                detail=str(e),
            )

    @with_postgres_session
    async def get_diet_plan(
        self,
        diet_plan_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[PatientDietPlanModel]:
        """Get a specific diet plan by ID."""
        try:
            stmt = select(PatientDietPlanModel).where(
                PatientDietPlanModel.diet_plan_id == diet_plan_id
            ).options(selectinload(PatientDietPlanModel.patient))
            result = await postgres_session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch diet plan.",
                detail=str(e),
            )

    @with_postgres_session
    async def update_diet_plan_status(
        self,
        diet_plan_id: str,
        new_status: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientDietPlanModel:
        """Update the status of a diet plan (ACTIVE, INACTIVE, ARCHIVED)."""
        try:
            stmt = select(PatientDietPlanModel).where(
                PatientDietPlanModel.diet_plan_id == diet_plan_id
            )
            result = await postgres_session.execute(stmt)
            diet_plan = result.scalars().first()

            if not diet_plan:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=f"Diet plan with ID '{diet_plan_id}' not found.",
                )

            diet_plan.status = new_status
            await postgres_session.commit()
            await postgres_session.refresh(diet_plan)
            return diet_plan
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to update diet plan status.",
                detail=str(e),
            )

    @with_postgres_session
    async def delete_diet_plan(
        self,
        diet_plan_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        """Delete a diet plan."""
        try:
            stmt = select(PatientDietPlanModel).where(
                PatientDietPlanModel.diet_plan_id == diet_plan_id
            )
            result = await postgres_session.execute(stmt)
            diet_plan = result.scalars().first()

            if not diet_plan:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=f"Diet plan with ID '{diet_plan_id}' not found.",
                )

            await postgres_session.delete(diet_plan)
            await postgres_session.commit()
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to delete diet plan.",
                detail=str(e),
            )

    # ==================== FITNESS PLAN METHODS ====================

    @with_postgres_session
    async def create_fitness_plan(
        self,
        patient_id: str,
        fitness_plan_data: PatientFitnessPlanCreate,
        start_date: datetime_date,
        end_date: Optional[datetime_date] = None,
        is_default: bool = False,
        status: str = "ACTIVE",
        plan_reason: Optional[str] = None,
        *,
        postgres_session: AsyncSession,
    ) -> PatientFitnessPlanModel:
        """Create a new fitness plan for a patient with date range and lifecycle fields."""
        try:
            # Check if trying to set is_default when another default exists
            if is_default:
                existing_default = await self.get_default_fitness_plan(
                    patient_id, postgres_session=postgres_session
                )
                if existing_default:
                    raise_http_exception(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message=f"Patient {patient_id} already has a default fitness plan.",
                    )

            fitness_plan = PatientFitnessPlanModel(
                patient_id=patient_id,
                start_date=start_date,
                end_date=end_date,
                is_default=is_default,
                status=status,
                plan_reason=plan_reason,
                **fitness_plan_data.model_dump(),
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
    async def get_active_fitness_plan(
        self,
        patient_id: str,
        query_date: Optional[datetime_date] = None,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[PatientFitnessPlanModel]:
        """Get the active fitness plan for a patient on a specific date."""
        try:
            if query_date is None:
                query_date = datetime.now().date()

            stmt = (
                select(PatientFitnessPlanModel)
                .where(
                    PatientFitnessPlanModel.patient_id == patient_id,
                    PatientFitnessPlanModel.status == "ACTIVE",
                    PatientFitnessPlanModel.start_date <= query_date,
                    or_(
                        PatientFitnessPlanModel.end_date.is_(None),
                        PatientFitnessPlanModel.end_date >= query_date,
                    ),
                )
                .order_by(PatientFitnessPlanModel.updated_at.desc())
            )

            result = await postgres_session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch active fitness plan.",
                detail=str(e),
            )

    @with_postgres_session
    async def get_default_fitness_plan(
        self,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[PatientFitnessPlanModel]:
        """Get the default fitness plan for a patient (set during onboarding)."""
        try:
            stmt = (
                select(PatientFitnessPlanModel)
                .where(
                    PatientFitnessPlanModel.patient_id == patient_id,
                    PatientFitnessPlanModel.is_default.is_(True),
                    PatientFitnessPlanModel.status == "ACTIVE",
                )
            )

            result = await postgres_session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch default fitness plan.",
                detail=str(e),
            )

    @with_postgres_session
    async def get_patient_fitness_plans(
        self,
        patient_id: str,
        status_filter: Optional[str] = None,
        *,
        postgres_session: AsyncSession,
    ) -> List[PatientFitnessPlanModel]:
        """Get all fitness plans for a patient, optionally filtered by status."""
        try:
            stmt = select(PatientFitnessPlanModel).where(
                PatientFitnessPlanModel.patient_id == patient_id
            )

            if status_filter:
                stmt = stmt.where(PatientFitnessPlanModel.status == status_filter)

            stmt = stmt.order_by(PatientFitnessPlanModel.start_date.desc())

            result = await postgres_session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch patient fitness plans.",
                detail=str(e),
            )

    @with_postgres_session
    async def get_fitness_plan(
        self,
        fitness_plan_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[PatientFitnessPlanModel]:
        """Get a specific fitness plan by ID."""
        try:
            stmt = select(PatientFitnessPlanModel).where(
                PatientFitnessPlanModel.fitness_plan_id == fitness_plan_id
            ).options(selectinload(PatientFitnessPlanModel.patient))
            result = await postgres_session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch fitness plan.",
                detail=str(e),
            )

    @with_postgres_session
    async def update_fitness_plan_status(
        self,
        fitness_plan_id: str,
        new_status: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientFitnessPlanModel:
        """Update the status of a fitness plan (ACTIVE, INACTIVE, ARCHIVED)."""
        try:
            stmt = select(PatientFitnessPlanModel).where(
                PatientFitnessPlanModel.fitness_plan_id == fitness_plan_id
            )
            result = await postgres_session.execute(stmt)
            fitness_plan = result.scalars().first()

            if not fitness_plan:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=f"Fitness plan with ID '{fitness_plan_id}' not found.",
                )

            fitness_plan.status = new_status
            await postgres_session.commit()
            await postgres_session.refresh(fitness_plan)
            return fitness_plan
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to update fitness plan status.",
                detail=str(e),
            )

    @with_postgres_session
    async def delete_fitness_plan(
        self,
        fitness_plan_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        """Delete a fitness plan."""
        try:
            stmt = select(PatientFitnessPlanModel).where(
                PatientFitnessPlanModel.fitness_plan_id == fitness_plan_id
            )
            result = await postgres_session.execute(stmt)
            fitness_plan = result.scalars().first()

            if not fitness_plan:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=f"Fitness plan with ID '{fitness_plan_id}' not found.",
                )

            await postgres_session.delete(fitness_plan)
            await postgres_session.commit()
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to delete fitness plan.",
                detail=str(e),
            )
