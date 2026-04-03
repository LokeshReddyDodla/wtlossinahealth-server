from datetime import date as datetime_date
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import status as responseStatus
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.core.postgres_store import PostgresStore
from lib.models.patient_fitness_plan import PatientFitnessPlan as PatientFitnessPlanModel
from lib.schemas.patient_fitness_plan import PatientFitnessPlanCreate
from lib.services.patient_profile_service import PatientProfileService
from lib.services.vector.plans import PlansVectorService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session

logger = __import__("logging").getLogger(__name__)


class PatientFitnessPlanService:
    """Service for managing patient fitness plans."""

    def __init__(
        self,
        postgres_store: PostgresStore,
        plans_vector_service: PlansVectorService,
        patient_profile_service: PatientProfileService,
    ):
        self.postgres_store = postgres_store
        self.plans_vector_service = plans_vector_service
        self.patient_profile_service = patient_profile_service

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
            if status == "ACTIVE":
                overlapping_stmt = select(PatientFitnessPlanModel).where(
                    PatientFitnessPlanModel.patient_id == patient_id,
                    PatientFitnessPlanModel.status == "ACTIVE",
                    PatientFitnessPlanModel.start_date
                    <= (end_date if end_date else datetime(9999, 12, 31).date()),
                    or_(
                        PatientFitnessPlanModel.end_date.is_(None),
                        PatientFitnessPlanModel.end_date >= start_date,
                    ),
                )
                result = await postgres_session.execute(overlapping_stmt)
                overlapping_plan = result.scalars().first()

                if overlapping_plan:
                    end_date_display = overlapping_plan.end_date.strftime('%B %d, %Y') if overlapping_plan.end_date else 'ongoing'
                    raise_http_exception(
                        status_code=responseStatus.HTTP_400_BAD_REQUEST,
                        message=f"You already have an active fitness plan from {overlapping_plan.start_date.strftime('%B %d, %Y')} to {end_date_display}. Please pause or archive it before creating a new one.",
                    )

            if is_default:
                existing_default = await self.get_default_fitness_plan(
                    patient_id, postgres_session=postgres_session
                )
                if existing_default:
                    raise_http_exception(
                        status_code=responseStatus.HTTP_400_BAD_REQUEST,
                        message="A default fitness plan already exists. Please update the existing one or remove its default status first.",
                    )

            fitness_plan = PatientFitnessPlanModel(
                patient_id=patient_id,
                **fitness_plan_data.model_dump(),
            )
            postgres_session.add(fitness_plan)
            await postgres_session.commit()
            await postgres_session.refresh(fitness_plan)

            await self._vectorize_fitness_plan(fitness_plan)

            return fitness_plan
        except IntegrityError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=responseStatus.HTTP_400_BAD_REQUEST,
                message="Unable to create fitness plan. Please check your inputs and try again.",
                detail=str(e),
            )

    @with_postgres_session
    async def replace_active_fitness_plan(
        self,
        patient_id: str,
        fitness_plan_data: PatientFitnessPlanCreate,
        start_date: datetime_date,
        end_date: Optional[datetime_date] = None,
        is_default: bool = False,
        plan_reason: Optional[str] = None,
        *,
        postgres_session: AsyncSession,
    ) -> PatientFitnessPlanModel:
        """Archive all current active fitness plans and create a new one (convenience method).

        This helper method:
        1. Finds all ACTIVE fitness plans for the patient
        2. Archives them and adjusts their end_date to day before new plan starts
        3. Creates the new ACTIVE fitness plan

        Use this when you want to replace the current plan with a new one.
        """
        try:
            active_plans = await self.get_patient_fitness_plans(
                patient_id=patient_id,
                status_filter="ACTIVE",
                postgres_session=postgres_session,
            )

            for plan in active_plans:
                plan.status = "ARCHIVED"
                if plan.end_date is None or plan.end_date >= start_date:
                    plan.end_date = start_date - timedelta(days=1)
                await self._vectorize_fitness_plan(plan)

            return await self.create_fitness_plan(
                patient_id=patient_id,
                fitness_plan_data=fitness_plan_data,
                start_date=start_date,
                end_date=end_date,
                is_default=is_default,
                status="ACTIVE",
                plan_reason=plan_reason,
                postgres_session=postgres_session,
            )
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=responseStatus.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Unable to update your fitness plan. Please try again.",
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
                status_code=responseStatus.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Unable to load your active fitness plan. Please try again.",
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
            stmt = select(PatientFitnessPlanModel).where(
                PatientFitnessPlanModel.patient_id == patient_id,
                PatientFitnessPlanModel.is_default.is_(True),
                PatientFitnessPlanModel.status == "ACTIVE",
            )

            result = await postgres_session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=responseStatus.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Unable to load your default fitness plan. Please try again.",
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
                status_code=responseStatus.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Unable to load fitness plans. Please try again.",
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
            stmt = (
                select(PatientFitnessPlanModel)
                .where(PatientFitnessPlanModel.fitness_plan_id == fitness_plan_id)
                .options(selectinload(PatientFitnessPlanModel.patient))
            )
            result = await postgres_session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=responseStatus.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Unable to load this fitness plan. Please try again.",
                detail=str(e),
            )

    @with_postgres_session
    async def update_fitness_plan(
        self,
        fitness_plan_id: str,
        update_data: dict,
        *,
        postgres_session: AsyncSession,
    ) -> PatientFitnessPlanModel:
        """Update a fitness plan with provided data."""
        try:
            stmt = select(PatientFitnessPlanModel).where(
                PatientFitnessPlanModel.fitness_plan_id == fitness_plan_id
            )
            result = await postgres_session.execute(stmt)
            fitness_plan = result.scalars().first()

            if not fitness_plan:
                raise_http_exception(
                    status_code=responseStatus.HTTP_404_NOT_FOUND,
                    message="Fitness plan not found. It may have been deleted.",
                )

            for field, value in update_data.items():
                if hasattr(fitness_plan, field):
                    setattr(fitness_plan, field, value)

            await postgres_session.commit()
            await postgres_session.refresh(fitness_plan)

            await self._vectorize_fitness_plan(fitness_plan)

            return fitness_plan
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=responseStatus.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Unable to save changes to your fitness plan. Please try again.",
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
                    status_code=responseStatus.HTTP_404_NOT_FOUND,
                    message="Fitness plan not found. It may have been deleted.",
                )

            fitness_plan.status = new_status
            await postgres_session.commit()
            await postgres_session.refresh(fitness_plan)

            await self._vectorize_fitness_plan(fitness_plan)

            if new_status != "ACTIVE":
                await self._expire_plan_tasks(str(fitness_plan.patient_id), str(fitness_plan.fitness_plan_id))

            return fitness_plan
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=responseStatus.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Unable to update fitness plan status. Please try again.",
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
                    status_code=responseStatus.HTTP_404_NOT_FOUND,
                    message="Fitness plan not found. It may have been deleted.",
                )

            patient_id = str(fitness_plan.patient_id)
            plan_id = str(fitness_plan.fitness_plan_id)
            await postgres_session.delete(fitness_plan)
            await postgres_session.commit()

            try:
                await self.plans_vector_service.delete_plan_vector(plan_id)
            except Exception as e:
                logger.error(f"Failed to delete fitness plan vector {plan_id}: {e}")

            await self._expire_plan_tasks(patient_id, plan_id)

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=responseStatus.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Unable to delete fitness plan. Please try again.",
                detail=str(e),
            )

    async def _vectorize_fitness_plan(self, plan: PatientFitnessPlanModel) -> None:
        """Fire-and-forget vectorization of a fitness plan."""
        try:
            patient = await self.patient_profile_service.fetch_patient_profile(str(plan.patient_id))
            plan_data = {
                "start_date": str(plan.start_date),
                "end_date": str(plan.end_date) if plan.end_date else None,
                "status": plan.status,
                "plan_reason": plan.plan_reason,
                "is_default": plan.is_default,
                "steps_goal": plan.steps_goal,
                "content": plan.content,
            }
            await self.plans_vector_service.upsert_fitness_plan_vector(
                patient_id=str(plan.patient_id),
                plan_id=str(plan.fitness_plan_id),
                plan_data=plan_data,
                patient_age=patient.age or 0,
                patient_gender=patient.gender or "unknown",
            )
        except Exception as e:
            logger.error(f"Failed to vectorize fitness plan {plan.fitness_plan_id}: {e}")

    async def _expire_plan_tasks(self, patient_id: str, plan_id: str) -> None:
        """Expire today's pending tasks that were derived from this plan."""
        try:
            from lib.models.gamification import DailyTask
            from lib.services.gamification.time_utils import local_today
            today = local_today(None)
            async with self.postgres_store.get_session() as session:
                result = await session.execute(
                    select(DailyTask).where(
                        DailyTask.patient_id == patient_id,
                        DailyTask.task_date == today,
                        DailyTask.source_id == plan_id,
                        DailyTask.status == "pending",
                    )
                )
                for task in result.scalars().all():
                    task.status = "expired"
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to expire plan tasks for {plan_id}: {e}")
