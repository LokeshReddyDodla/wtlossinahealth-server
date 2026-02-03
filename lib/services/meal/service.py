import json
from datetime import date, datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import status
from sqlalchemy import asc, delete, desc, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.core.postgres_store import PostgresStore
from lib.models.patient_meal import PatientFoodItem as PatientFoodItemModel
from lib.models.patient_meal import PatientMeal as PatientMealModel
from lib.models.patient_meal import (
    PatientTotalMacroNutritionalValue as PatientTotalMacroNutritionalValueModel,
)
from lib.models.patient_meal import (
    PatientTotalMicroNutritionalValue as PatientTotalMicroNutritionalValueModel,
)
from lib.schemas.patient import CorePatientProfile
from lib.schemas.patient_meal import MealAnalysisResponse
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.services.vector import MealVectorService
from lib.services.patient_profile_service import PatientProfileService
from lib.workers.tasks.meal.enqueue import enqueue_daily_meal_report_sync
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session
from rest_server.patients.meals.api_schema import (
    PatientMealUpdateRequest,
    PatientMealUploadRequest,
)

from .analysis import MealAnalysisService
from .helpers import (
    create_food_item,
    generate_conversation_flow,
    trigger_meal_tasks,
)


class MealService:
    """Main meal service that orchestrates meal operations."""

    def __init__(
        self,
        postgres_store: PostgresStore,
        meal_analysis_service: MealAnalysisService,
        patient_profile_service: PatientProfileService,
        meal_vector_service: MealVectorService,
    ):
        self.postgres_store = postgres_store
        self.meal_analysis_service = meal_analysis_service
        self.patient_profile_service = patient_profile_service
        self.meal_vector_service = meal_vector_service
        self.ai_conversation_service = AiConversationService(
            conversation_type="meal",
            selected_ai_model="gpt-4.1-mini",
            ai_model_provider="openai",
        )

    @with_postgres_session
    async def fetch_meals(
        self,
        patient_id: str,
        start_datetime: Optional[datetime] = None,
        end_datetime: Optional[datetime] = None,
        source: Optional[str] = None,
        analyzed: Optional[str] = None,
        order_by: Optional[str] = "time",
        order: Optional[str] = "asc",
        limit: Optional[int] = None,
        *,
        postgres_session: AsyncSession,
    ):
        try:
            query = (
                select(PatientMealModel)
                .where(PatientMealModel.patient_id == patient_id)
                .options(
                    selectinload(PatientMealModel.items).selectinload(
                        PatientFoodItemModel.macro_nutritional_values
                    ),
                    selectinload(PatientMealModel.items).selectinload(
                        PatientFoodItemModel.micro_nutritional_values
                    ),
                    selectinload(PatientMealModel.total_macro_nutritional_value),
                    selectinload(PatientMealModel.total_micro_nutritional_value),
                )
            )

            if start_datetime:
                query = query.filter(
                    (PatientMealModel.date > start_datetime.date())
                    | (
                        (PatientMealModel.date == start_datetime.date())
                        & (PatientMealModel.time >= start_datetime.time())
                    )
                )
            if end_datetime:
                query = query.filter(
                    (PatientMealModel.date < end_datetime.date())
                    | (
                        (PatientMealModel.date == end_datetime.date())
                        & (PatientMealModel.time <= end_datetime.time())
                    )
                )

            if source:
                query = query.filter(PatientMealModel.source == source)
            if analyzed == "true":
                query = query.filter(PatientMealModel.analyzed.is_(True))
            elif analyzed == "false":
                query = query.filter(PatientMealModel.analyzed.is_(False))

            if order_by == "time":
                if order == "asc":
                    query = query.order_by(asc(PatientMealModel.time))
                else:
                    query = query.order_by(desc(PatientMealModel.time))
            elif order_by == "created_at":
                if order == "asc":
                    query = query.order_by(asc(PatientMealModel.uploaded_at))
                else:
                    query = query.order_by(desc(PatientMealModel.uploaded_at))

            if limit:
                query = query.limit(limit)

            result = await postgres_session.execute(query)
            return result.scalars().all()
        except Exception as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Internal Server Error",
                detail=str(e),
            )

    @with_postgres_session
    async def fetch_meal(
        self, meal_id: str, *, postgres_session: AsyncSession
    ) -> PatientMealModel:
        query = (
            select(PatientMealModel)
            .where(PatientMealModel.id == meal_id)
            .options(
                selectinload(PatientMealModel.items).selectinload(
                    PatientFoodItemModel.macro_nutritional_values
                ),
                selectinload(PatientMealModel.items).selectinload(
                    PatientFoodItemModel.micro_nutritional_values
                ),
                selectinload(PatientMealModel.total_macro_nutritional_value),
                selectinload(PatientMealModel.total_micro_nutritional_value),
            )
        )

        result = await postgres_session.execute(query)
        meal = result.scalars().first()

        if not meal:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Meal not found",
            )

        return meal

    @with_postgres_session
    async def get_meal_counts_by_date(
        self,
        patient_id: str,
        start_date: date,
        end_date: date,
        *,
        postgres_session: AsyncSession,
    ) -> List[dict]:
        try:
            query = (
                select(
                    PatientMealModel.date,
                    func.count(PatientMealModel.id).label("meal_count"),
                )
                .where(
                    PatientMealModel.patient_id == patient_id,
                    PatientMealModel.date >= start_date,
                    PatientMealModel.date <= end_date,
                )
                .group_by(PatientMealModel.date)
                .order_by(PatientMealModel.date)
            )

            result = await postgres_session.execute(query)
            records = result.all()

            return [
                {
                    "date": record.date.isoformat(),
                    "meal_count": record.meal_count,
                }
                for record in records
            ]

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def upload_meal(
        self,
        meal_data: PatientMealUploadRequest,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientMealModel:
        try:
            meal = PatientMealModel(
                type=meal_data.type,
                time=meal_data.datetime.time(),
                date=meal_data.datetime.date(),
                source=meal_data.source,
                description=meal_data.description,
                image_url=(str(meal_data.image_url) if meal_data.image_url else None),
                patient_id=patient_id,
            )

            postgres_session.add(meal)
            await postgres_session.commit()
            await postgres_session.refresh(meal)

            enqueue_daily_meal_report_sync(str(patient_id), meal.date)

            return meal

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def update_meal(
        self,
        meal_id: str,
        update_data: PatientMealUpdateRequest,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientMealModel:
        try:
            meal = await self.fetch_meal(meal_id, postgres_session=postgres_session)

            meal.type = update_data.type
            meal.time = update_data.datetime.time()
            meal.date = update_data.datetime.date()
            meal.source = update_data.source
            if update_data.description is not None:
                meal.description = update_data.description
            if update_data.image_url is not None:
                meal.image_url = (
                    str(update_data.image_url) if update_data.image_url else None
                )

            meal.analyzed = False
            meal.analyzed_at = None
            meal.score = None
            meal.feedback = None
            meal.tags = None

            for item in meal.items:
                await postgres_session.delete(item)

            if meal.total_macro_nutritional_value:
                await postgres_session.delete(meal.total_macro_nutritional_value)
            if meal.total_micro_nutritional_value:
                await postgres_session.delete(meal.total_micro_nutritional_value)

            await postgres_session.commit()
            await postgres_session.refresh(meal)

            enqueue_daily_meal_report_sync(str(patient_id), meal.date)

            return meal

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def analyze_or_reanalyze_meal(
        self,
        meal_id: str,
        patient_id: str,
        re_analyze: Optional[bool] = False,
        update_fields: Optional[dict] = None,
        *,
        postgres_session: AsyncSession,
    ) -> PatientMealModel:
        try:
            meal = await self.fetch_meal(meal_id, postgres_session=postgres_session)
            meal_orm = PatientMealSchema.model_validate(meal)

            if meal_orm.analyzed and not re_analyze:
                return meal

            parsed_ai_response = await self._perform_meal_analysis(
                meal, meal_orm, patient_id, update_fields
            )

            if not parsed_ai_response:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=f"Meal with ID {meal_id} failed to be analyzed",
                )

            updated_meal = await self.save_meal_analysis(
                meal, parsed_ai_response, postgres_session=postgres_session
            )

            if re_analyze:
                await self.ai_conversation_service.delete_conversation_messages(
                    conversation_id=meal_id
                )

            await self._create_meal_conversation(meal_orm, meal_id, parsed_ai_response)
            trigger_meal_tasks(str(patient_id), str(meal_id), meal.date, updated_meal)

            return updated_meal
        except (json.JSONDecodeError, SQLAlchemyError) as e:
            await postgres_session.rollback()
            status_code = (
                status.HTTP_400_BAD_REQUEST
                if isinstance(e, json.JSONDecodeError)
                else status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            raise_http_exception(
                status_code=status_code,
                message="Invalid JSON"
                if isinstance(e, json.JSONDecodeError)
                else "Database Error",
                detail=str(e),
            )

    async def _perform_meal_analysis(
        self,
        meal: PatientMealModel,
        meal_orm: PatientMealSchema,
        patient_id: str,
        update_fields: Optional[dict],
    ) -> MealAnalysisResponse:
        if update_fields:
            if "description" in update_fields:
                meal.description = update_fields["description"]
            return await self.meal_analysis_service.reanalyze_meal(
                patient_id, meal_orm.model_dump(), update_fields
            )

        patient = await self.patient_profile_service.fetch_patient_profile(
            patient_id=patient_id, detailed=True
        )
        patient_profile_json = CorePatientProfile.from_orm(patient).model_dump()

        return await self.meal_analysis_service.analyze_meal(
            patient_id,
            patient_profile_json,
            meal.time,
            meal.image_url,
            meal.type,
            meal.description,
        )

    async def _create_meal_conversation(
        self,
        meal_orm: PatientMealSchema,
        meal_id: str,
        parsed_ai_response: MealAnalysisResponse,
    ):
        message_sequence = generate_conversation_flow(
            meal_orm, meal_id, parsed_ai_response
        )
        await self.ai_conversation_service.add_multiple_messages_to_conversation(
            messages=message_sequence,
        )

    @with_postgres_session
    async def save_meal_analysis(
        self,
        meal: Any,
        analysis_data: MealAnalysisResponse,
        *,
        postgres_session: AsyncSession,
    ) -> PatientMealModel:
        meal.items = [
            create_food_item(meal, item_data) for item_data in analysis_data.items
        ]

        total_macro = analysis_data.total_macro_nutritional_value.model_dump()
        meal.total_macro_nutritional_value = PatientTotalMacroNutritionalValueModel(
            meal_id=meal.id, **total_macro
        )

        total_micro = analysis_data.total_micro_nutritional_value.model_dump()
        meal.total_micro_nutritional_value = PatientTotalMicroNutritionalValueModel(
            meal_id=meal.id, **total_micro
        )

        meal.name = analysis_data.meal_name
        meal.feedback = analysis_data.feedback
        meal.tags = analysis_data.tags
        meal.score = float(analysis_data.score)
        meal.analyzed = True
        meal.analyzed_at = datetime.now()

        await postgres_session.merge(meal)
        await postgres_session.commit()

        return meal

    @with_postgres_session
    async def delete_meal(
        self, meal_id: UUID, patient_id: str, *, postgres_session: AsyncSession
    ):
        try:
            meal = await self.fetch_meal(
                str(meal_id), postgres_session=postgres_session
            )
            meal_date = meal.date

            await postgres_session.delete(meal)
            await postgres_session.commit()

            enqueue_daily_meal_report_sync(str(patient_id), meal_date)
            await self.meal_vector_service.delete_meal_vector(str(meal_id))

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def delete_all_meals_for_patient(
        self, patient_id: str, *, postgres_session: AsyncSession
    ):
        try:
            await postgres_session.execute(
                delete(PatientMealModel).where(
                    PatientMealModel.patient_id == patient_id
                )
            )
            await postgres_session.commit()

            await self.meal_vector_service.delete_meal_vectors_for_patient(patient_id)

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )
