import json
from datetime import date, datetime
from typing import List, Optional
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
from rest_server.patients.meals.api_schema import PatientMealUploadRequest


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
            selected_ai_model="gpt-4o-mini",
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

            updated_meal = await self.meal_analysis_service.save_meal_analysis(
                meal, parsed_ai_response
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
        self, meal_id: UUID, *, postgres_session: AsyncSession
    ):
        try:
            result = await postgres_session.execute(
                select(PatientMealModel).where(PatientMealModel.id == meal_id)
            )
            meal = result.scalars().first()

            if not meal:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Meal not found.",
                )

            patient_id = meal.patient_id
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
