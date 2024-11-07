import json
import uuid
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from markdownify import markdownify as md
from sqlalchemy import asc, delete, desc
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.models.patient_meal import PatientFoodItem as PatientFoodItemModel
from lib.models.patient_meal import PatientMeal as PatientMealModel
from lib.schemas.ai_conversation_schemas import \
    AiConversationMessage as AiConversationMessageSchema
from lib.schemas.patient import CorePatientProfile
from lib.schemas.patient_meal import MealAnalysisResponse
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema
from lib.services.ai_conversation_service import AiConversationService
from lib.services.meal_analysis_service import MealAnalysisService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.patient_token_usage_logger import PatientTokenUsageLogger
from rest_server.patients.meals.api_schema import PatientMealUploadRequest
from rest_server.response_models import ErrorResponse


class MealService:
    def __init__(
        self,
        postgres_session: AsyncSession,
        meal_analysis_service: MealAnalysisService,
        patient_profile_service: PatientProfileService,
    ):
        self.postgres_session = postgres_session
        self.meal_analysis_service = meal_analysis_service
        self.patient_profile_service = patient_profile_service
        self.ai_conversation_service = AiConversationService(
            "meal", model="gpt-4o-mini"
        )

    async def fetch_meals(
        self,
        patient_id: str,
        from_datetime: Optional[datetime] = None,
        to_datetime: Optional[datetime] = None,
        source: Optional[str] = None,
        analyzed: Optional[str] = None,
        order_by: Optional[str] = "time",
        order: Optional[str] = "asc",
        limit: Optional[int] = None,
    ):
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

        if from_datetime:
            query = query.filter(
                (PatientMealModel.date > from_datetime.date())
                | (
                    (PatientMealModel.date == from_datetime.date())
                    & (PatientMealModel.time >= from_datetime.time())
                )
            )
        if to_datetime:
            query = query.filter(
                (PatientMealModel.date < to_datetime.date())
                | (
                    (PatientMealModel.date == to_datetime.date())
                    & (PatientMealModel.time <= to_datetime.time())
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

        result = await self.postgres_session.execute(query)
        meals = result.scalars().all()

        return meals

    async def fetch_meal(self, meal_id: str) -> PatientMealModel:
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

        result = await self.postgres_session.execute(query)
        meal = result.scalars().first()

        if not meal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found.",
            )

        return meal

    async def upload_meal(
        self, meal_data: PatientMealUploadRequest, patient_id: str
    ) -> PatientMealModel:
        try:
            meal = PatientMealModel(
                type=meal_data.type,
                time=meal_data.datetime.time(),
                date=meal_data.datetime.date(),
                source=meal_data.source,
                description=meal_data.description,
                image_url=str(meal_data.image_url),
                patient_id=patient_id,
            )

            self.postgres_session.add(meal)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(meal)

            return meal

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=500, detail=f"Database Error: {str(e)}"
            )

    async def analyze_meal(
        self,
        meal_id: str,
        patient_id: str,
        re_analyze: Optional[bool] = False,
    ) -> PatientMealModel:
        try:
            meal = await self.fetch_meal(meal_id)
            meal_orm = PatientMealSchema.model_validate(meal)

            if meal_orm.analyzed and not re_analyze:
                return meal

            # Fetch patient Profile
            patient = await self.patient_profile_service.fetch_patient_profile(
                patient_id=patient_id, detailed=True
            )
            patient_profile_json = CorePatientProfile.from_orm(
                patient
            ).model_dump()

            # Analyze the meal using the MealAnalysisService
            (
                parsed_ai_response,
                tokens_used,
            ) = self.meal_analysis_service.analyze_meal(
                patient_profile_json,
                meal.time,
                meal.image_url,
                meal.type,
                meal.description,
            )

            if not parsed_ai_response:
                raise HTTPException(
                    status_code=400,
                    detail=f"Meal with ID {meal_id} failed to be analyzed",
                )

            updated_meal = await self.meal_analysis_service.save_meal_analysis(
                meal, parsed_ai_response
            )

            if re_analyze:
                self.ai_conversation_service.delete_conversation_messages(
                    conversation_id=meal_id
                )

            # Define custom conversation flow for meals
            message_sequence = [
                AiConversationMessageSchema(
                    patient_id=str(meal_orm.patient_id),
                    conversation_id=meal_id,
                    conversation_type="meal",
                    role="human",
                    message_type="markdown",
                    content=md(
                        f"I had **{meal_orm.type}** at **{meal_orm.time.strftime('%I:%M %p')}**."
                    ),
                ),
                AiConversationMessageSchema(
                    patient_id=str(meal_orm.patient_id),
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
                    patient_id=str(meal_orm.patient_id),
                    conversation_id=meal_id,
                    conversation_type="meal",
                    role="ai",
                    message_type="text",
                    content=parsed_ai_response.model_dump_json(),
                    exclude_from_frontend=True,
                ),
                AiConversationMessageSchema(
                    patient_id=str(meal_orm.patient_id),
                    conversation_id=meal_id,
                    conversation_type="meal",
                    role="system",
                    message_type="text",
                    content="How can I assist you further regarding this meal?",
                ),
            ]

            # Pass the message sequence to AiConversationService
            self.ai_conversation_service.add_messages_to_conversation(
                messages=message_sequence,
            )

            # Log token usage if applicable
            if tokens_used:
                await PatientTokenUsageLogger.log_usage(
                    patient_id=UUID(patient_id),
                    tokens_used=tokens_used,
                    model_used="gpt-4o",
                    api_type="openai",
                    api_endpoint="/patient/meals/analyze",
                )

            return updated_meal
        except json.JSONDecodeError as e:
            await self.postgres_session.rollback()
            response = ErrorResponse(message="Invalid JSON", detail=str(e))
            raise HTTPException(status_code=400, detail=response.model_dump())
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database Error: {str(e)}",
            )

    async def delete_meal(self, meal_id: UUID):
        try:

            result = await self.postgres_session.execute(
                select(PatientMealModel).where(PatientMealModel.id == meal_id)
            )
            meal = result.scalars().first()

            if not meal:
                raise HTTPException(status_code=404, detail="Meal not found")

            await self.postgres_session.delete(meal)
            await self.postgres_session.commit()
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database Error: {str(e)}",
            )

    async def delete_all_meals_for_patient(self, patient_id: str):
        try:
            await self.postgres_session.execute(
                delete(PatientMealModel).where(
                    PatientMealModel.patient_id == patient_id
                )
            )
            await self.postgres_session.commit()

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database Error: {str(e)}",
            )
