import json
import uuid
from datetime import datetime
from typing import Optional, Union
from uuid import UUID

from decouple import config
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.managers.context_manager import context_manager
from lib.models.patient import Patient
from lib.models.patient_meal import PatientFoodItem, PatientMeal
from lib.services.meal_analysis_service import MealAnalysisService
from lib.utils.json_parsing import parse_json_garbage
from lib.utils.openai.meal_analysis import get_nutritional_info
from lib.utils.patient_token_usage_logger import PatientTokenUsageLogger
from rest_server.patients.meals.api_schema import (PatientMealAnalysisResponse,
                                                   PatientMealResponse)
from rest_server.response_models import ErrorResponse

from .router import router


@router.post(
    path="/analyze",
    response_model=PatientMealAnalysisResponse,
)
async def analyze_meal_api(
    request: Request,
    meal_id: str,
    re_analyze: Optional[bool] = False,
    session: AsyncSession = Depends(get_postgres_session),
    current_patient: Patient = Depends(get_current_patient),
):
    """
    Analyze Meal API
    """
    try:
        # Fetch the meal entry by ID
        meal_query = await session.execute(
            select(PatientMeal)
            .filter(
                PatientMeal.id == meal_id,
                PatientMeal.patient_id == current_patient.patient_id,
            )
            .options(
                selectinload(PatientMeal.items).selectinload(
                    PatientFoodItem.macro_nutritional_values
                ),
                selectinload(PatientMeal.items).selectinload(
                    PatientFoodItem.micro_nutritional_values
                ),
                selectinload(PatientMeal.total_macro_nutritional_value),
                selectinload(PatientMeal.total_micro_nutritional_value),
            )
        )
        meal = meal_query.scalars().first()

        if not meal:
            response = ErrorResponse(
                message="Meal not found",
                detail=f"Meal with ID {meal_id} not found",
            )
            raise HTTPException(status_code=404, detail=response.dict())

        if meal.analyzed and not re_analyze:
            return PatientMealAnalysisResponse(
                message="Meal analyzed successfully.",
                data=PatientMealResponse.from_orm(meal),
            )

        meal_analysis_service = MealAnalysisService(
            session, api_key=config("OPENAI_API_KEY")
        )
        ai_response, tokens_used = meal_analysis_service.analyze_meal(
            meal.time,
            meal.image_url,
            meal.type,
            meal.description,
        )

        if not ai_response:
            response = ErrorResponse(
                message="Analysis failed",
                detail=f"Meal with ID {meal_id} failed to be analyzed",
            )
            raise HTTPException(status_code=400, detail="")

        analysis_data = json.loads(ai_response)
        updated_meal_response = await meal_analysis_service.save_meal_analysis(
            meal, analysis_data
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

        return PatientMealAnalysisResponse(
            message="Meal analyzed successfully.",
            data=updated_meal_response,
        )
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
