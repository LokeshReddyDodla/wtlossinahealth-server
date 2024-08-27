from datetime import datetime
import json
from typing import Optional, Union
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient
from lib.models.meal import (
    Meal,
    FoodItem,
)
from lib.schemas.meal import MealResponse
from lib.services.meal_analysis_service import MealAnalysisService
from lib.utils.json_parsing import parse_json_garbage
from lib.utils.openai.meal_analysis import get_nutritional_info
from lib.utils.patient_token_usage_logger import PatientTokenUsageLogger
from rest_server.meals.api_schema import MealAnalysisResponse
from rest_server.response_models import ErrorResponse
from lib.managers.context_manager import context_manager
from sqlalchemy.orm import selectinload
from uuid import UUID
from decouple import config


# Create FastAPI router
router = APIRouter(prefix="/patient/meals")


@router.post(path="/analyze", response_model=MealResponse, tags=["Meal"])
async def analyze_meal_api(
    request: Request,
    meal_id: str,
    force: Optional[bool] = False,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[MealResponse, HTTPException]:
    """
    Analyse Meal API
    """
    async with request.state.context.postgres_store.get_session() as session:
        try:
            # Fetch the meal entry by ID
            meal_query = await session.execute(
                select(Meal)
                .filter(
                    Meal.id == meal_id,
                    Meal.patient_id == current_patient.patient_id,
                )
                .options(
                    selectinload(Meal.items).selectinload(
                        FoodItem.macro_nutritional_values
                    ),
                    selectinload(Meal.items).selectinload(
                        FoodItem.micro_nutritional_values
                    ),
                    selectinload(Meal.total_macro_nutritional_value),
                    selectinload(Meal.total_micro_nutritional_value),
                )
            )
            meal = meal_query.scalars().first()

            if not meal:
                response = ErrorResponse(
                    message="Meal not found",
                    detail=f"Meal with ID {meal_id} not found",
                )
                raise HTTPException(status_code=404, detail=response.dict())

            if meal.analyzed and not force:
                return MealResponse.from_orm(meal)

            meal_analysis_service = MealAnalysisService(
                session, api_key=config("OPENAI_API_KEY")
            )
            ai_response, tokens_used = meal_analysis_service.analyze_meal(
                meal.time.timestamp(), meal.image_url, meal.description
            )

            if not ai_response:
                response = ErrorResponse(
                    message="Analysis failed",
                    detail=f"Meal with ID {meal_id} failed to be analysed",
                )
                raise HTTPException(status_code=400, detail="")

            analysis_data = json.loads(ai_response)
            updated_meal_response = (
                await meal_analysis_service.save_meal_analysis(
                    meal, analysis_data
                )
            )

            # context_manager.add_message(
            #     meal.context_id,
            #     ai_response or "",
            #     "assistant",
            #     "meal",
            #     media_url=meal.image_url,
            # )

            # Log token usage
            if tokens_used is not None:
                await PatientTokenUsageLogger.log_usage(
                    session,
                    patient_id=UUID(str(current_patient.patient_id)),
                    tokens_used=tokens_used,
                    model_used="gpt-4o",
                    api_type="openai",
                    api_endpoint=request.url.path,
                )

            return updated_meal_response
        except json.JSONDecodeError as e:
            await session.rollback()
            response = ErrorResponse(message="Invalid JSON", detail=str(e))
            raise HTTPException(status_code=400, detail=response.dict())
        except HTTPException as http_exc:
            await session.rollback()
            raise http_exc
        except Exception as e:
            await session.rollback()
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=400, detail=response.dict())
