import json
from datetime import date, datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import status
from markdownify import markdownify as md
from sqlalchemy import asc, delete, desc, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.core.constants import ProfileTypeEnum
from lib.core.postgres_store import PostgresStore
from lib.models.patient_meal import PatientFoodItem as PatientFoodItemModel
from lib.models.patient_meal import PatientMeal as PatientMealModel
from lib.schemas.ai_conversation_schemas import (
    AiConversationMessage as AiConversationMessageSchema,
)
from lib.schemas.patient import CorePatientProfile
from lib.schemas.patient_meal import MealAnalysisResponse
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.services.meal_analysis_service import MealAnalysisService
from lib.services.patient_profile_service import PatientProfileService
from lib.tasks.meal_tasks import generate_daily_meal_report
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session
from rest_server.patients.meals.api_schema import (
    PatientMealUpdateRequest,
    PatientMealUploadRequest,
)
from lib.models.patient_meal import PatientFoodItem as PatientFoodItemModel
from lib.models.patient_meal import (
    PatientMacroNutritionalValue as PatientMacroNutritionalValueModel,
)
from lib.models.patient_meal import PatientMeal as PatientMealModel
from lib.models.patient_meal import (
    PatientMicroNutritionalValue as PatientMicroNutritionalValueModel,
)
from lib.models.patient_meal import (
    PatientTotalMacroNutritionalValue as PatientTotalMacroNutritionalValueModel,
)
from lib.models.patient_meal import (
    PatientTotalMicroNutritionalValue as PatientTotalMicroNutritionalValueModel,
)
from lib.schemas.patient_meal import MealAnalysisResponse
from lib.schemas.patient_meal import PatientFoodItem as PatientFoodItemSchema
from lib.schemas.patient_meal import (
    PatientMacroNutritionalValue as PatientMacroNutritionalValueSchema,
)
from lib.schemas.patient_meal import (
    PatientMicroNutritionalValue as PatientMicroNutritionalValueSchema,
)


class MealService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        meal_analysis_service: MealAnalysisService,
        patient_profile_service: PatientProfileService,
    ):
        from lib.dependencies.service_dependencies import (
            get_token_usage_service,
        )

        self.postgres_store = postgres_store
        self.meal_analysis_service = meal_analysis_service
        self.patient_profile_service = patient_profile_service
        self.ai_conversation_service = AiConversationService(
            conversation_type="meal",
            selected_ai_model="gpt-5-mini",
            ai_model_provider="openai",
        )
        self.token_usage_service = get_token_usage_service()

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
                    selectinload(
                        PatientMealModel.total_macro_nutritional_value
                    ),
                    selectinload(
                        PatientMealModel.total_micro_nutritional_value
                    ),
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
                query = query.filter(PatientMealModel.analyzed == True)
            elif analyzed == "false":
                query = query.filter(PatientMealModel.analyzed == False)

            # Add ordering
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

            # Apply limit if provided
            if limit:
                query = query.limit(limit)

            result = await postgres_session.execute(query)
            meals = result.scalars().all()

            return meals
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
                image_url=(
                    str(meal_data.image_url) if meal_data.image_url else None
                ),
                patient_id=patient_id,
            )

            postgres_session.add(meal)
            await postgres_session.commit()
            await postgres_session.refresh(meal)

            # 🚀 Trigger Meal Report Generation after Upload
            generate_daily_meal_report.delay(str(patient_id), meal.date)

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
            meal = await self.fetch_meal(
                meal_id, postgres_session=postgres_session
            )

            # Update basic fields
            meal.type = update_data.type
            meal.time = update_data.datetime.time()
            meal.date = update_data.datetime.date()
            meal.source = update_data.source
            if update_data.description is not None:
                meal.description = update_data.description
            if update_data.image_url is not None:
                meal.image_url = (
                    str(update_data.image_url)
                    if update_data.image_url
                    else None
                )

            # Clear all analysis-related data
            meal.analyzed = False
            meal.analyzed_at = None
            meal.score = None
            meal.feedback = None
            meal.tags = None

            # Delete all related items and their nutritional values
            for item in meal.items:
                await postgres_session.delete(item)

            # Delete total nutritional values if they exist
            if meal.total_macro_nutritional_value:
                await postgres_session.delete(
                    meal.total_macro_nutritional_value
                )
            if meal.total_micro_nutritional_value:
                await postgres_session.delete(
                    meal.total_micro_nutritional_value
                )

            await postgres_session.commit()
            await postgres_session.refresh(meal)

            # Trigger report generation
            generate_daily_meal_report.delay(str(patient_id), meal.date)

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
            meal = await self.fetch_meal(
                meal_id, postgres_session=postgres_session
            )
            meal_orm = PatientMealSchema.model_validate(meal)

            if meal_orm.analyzed and not re_analyze:
                return meal

            # Fetch patient Profile
            patient = await self.patient_profile_service.fetch_patient_profile(
                patient_id=patient_id, detailed=True
            )  # type: ignore
            patient_profile_json = CorePatientProfile.from_orm(
                patient
            ).model_dump()

            # Analyze or reanalyze the meal using the MealAnalysisService
            if update_fields:
                if "description" in update_fields:
                    meal.description = update_fields["description"]

                parsed_ai_response = (
                    await self.meal_analysis_service.reanalyze_meal(
                        patient_id, meal_orm.model_dump(), update_fields
                    )
                )
            else:
                parsed_ai_response = (
                    await self.meal_analysis_service.analyze_meal(
                        patient_id,
                        patient_profile_json,
                        meal.time,
                        meal.image_url,
                        meal.type,
                        meal.description,
                    )
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

            # Define custom conversation flow for meals
            message_sequence = self._generate_conversation_flow(
                meal_orm, meal_id, parsed_ai_response
            )

            # Pass the message sequence to AiConversationService
            await self.ai_conversation_service.add_multiple_messages_to_conversation(
                messages=message_sequence,
            )

            # 🚀 Trigger Meal Report Generation after Analysis
            generate_daily_meal_report.delay(str(patient_id), meal.date)

            return updated_meal
        except json.JSONDecodeError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Invalid JSON",
                detail=str(e),
            )
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def save_meal_analysis(
        self,
        meal: Any,
        analysis_data: MealAnalysisResponse,
        *,
        postgres_session: AsyncSession,
    ) -> PatientMealModel:
        # create FoodItem records
        meal.items = [
            self._create_food_item(meal, item_data)
            for item_data in analysis_data.items
        ]

        # Update total macro nutritional values
        total_macro = analysis_data.total_macro_nutritional_value.model_dump()
        meal.total_macro_nutritional_value = (
            PatientTotalMacroNutritionalValueModel(
                meal_id=meal.id, **total_macro
            )
        )

        # Update total micro nutritional values
        total_micro = analysis_data.total_micro_nutritional_value.model_dump()
        meal.total_micro_nutritional_value = (
            PatientTotalMicroNutritionalValueModel(
                meal_id=meal.id, **total_micro
            )
        )

        # Update other meal fields
        meal.name = analysis_data.meal_name
        meal.feedback = analysis_data.feedback
        meal.tags = analysis_data.tags
        meal.score = float(analysis_data.score)
        meal.analyzed = True
        meal.analyzed_at = datetime.now()

        # Commit changes to the database
        await postgres_session.merge(meal)
        await postgres_session.commit()

        return meal

    def _create_food_item(
        self, meal: PatientMealModel, item_data: PatientFoodItemSchema
    ) -> PatientFoodItemModel:
        food_item = PatientFoodItemModel(
            name=item_data.name,
            coordinates=item_data.coordinates,
            serving_size=item_data.serving_size,
            serving_quantity=float(item_data.serving_quantity),
            serving_unit=item_data.serving_unit,
            category=item_data.category,
            meal=meal,
        )
        food_item.macro_nutritional_values = PatientMacroNutritionalValueModel(
            food_item_id=food_item.id,
            **item_data.macro_nutritional_values.model_dump(),
        )
        food_item.micro_nutritional_values = PatientMicroNutritionalValueModel(
            food_item_id=food_item.id,
            **item_data.micro_nutritional_values.model_dump(),
        )
        return food_item

    def _upsert_total_macro_nutritional_value(
        self,
        meal: PatientMealModel,
        macro_data: PatientMacroNutritionalValueSchema,
    ) -> PatientTotalMacroNutritionalValueModel:
        return PatientTotalMacroNutritionalValueModel(meal=meal, **macro_data)

    def _upsert_total_micro_nutritional_value(
        self,
        meal: PatientMealModel,
        micro_data: PatientMicroNutritionalValueSchema,
    ) -> PatientTotalMicroNutritionalValueModel:
        return PatientTotalMicroNutritionalValueModel(meal=meal, **micro_data)

    def _generate_conversation_flow(
        self, meal_orm, meal_id: str, parsed_ai_response: MealAnalysisResponse
    ) -> List[AiConversationMessageSchema]:
        return [
            AiConversationMessageSchema(
                user_id=str(meal_orm.patient_id),
                user_type=ProfileTypeEnum.PATIENT,
                conversation_id=meal_id,
                conversation_type="meal",
                role="human",
                message_type="markdown",
                content=md(
                    f"I had **{meal_orm.type}** at **{meal_orm.time.strftime('%I:%M %p')}**."
                ),
            ),
            AiConversationMessageSchema(
                user_id=str(meal_orm.patient_id),
                user_type=ProfileTypeEnum.PATIENT,
                conversation_id=meal_id,
                conversation_type="meal",
                role="human",
                message_type="image" if meal_orm.image_url else "text",
                content=(
                    str(meal_orm.image_url)
                    if meal_orm.image_url
                    else meal_orm.description or ""
                ),
            ),
            AiConversationMessageSchema(
                user_id=str(meal_orm.patient_id),
                user_type=ProfileTypeEnum.PATIENT,
                conversation_id=meal_id,
                conversation_type="meal",
                role="ai",
                message_type="text",
                content=parsed_ai_response.model_dump_json(),
                exclude_from_frontend=True,
            ),
            AiConversationMessageSchema(
                user_id=str(meal_orm.patient_id),
                user_type=ProfileTypeEnum.PATIENT,
                conversation_id=meal_id,
                conversation_type="meal",
                role="ai",
                message_type="text",
                content="How can I assist you further regarding this meal?",
            ),
        ]

    @with_postgres_session
    async def delete_meal(
        self, meal_id: UUID, patient_id: str, *, postgres_session: AsyncSession
    ):
        try:
            result = await postgres_session.execute(
                select(PatientMealModel).where(
                    PatientMealModel.id == meal_id,
                    PatientMealModel.patient_id == patient_id,
                )
            )
            meal = result.scalars().first()

            if not meal:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Meal not found.",
                )

            meal_date = meal.date

            await postgres_session.delete(meal)
            await postgres_session.commit()

            # 🚀 Trigger Meal Report Generation after Deletion
            generate_daily_meal_report.delay(str(patient_id), meal_date)

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

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )
