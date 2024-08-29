from typing import List, Optional, Union
from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import asc, desc
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient

from lib.models.patient_meal import PatientFoodItem, PatientMeal
from rest_server.patients.meals.api_schema import (
    PatientMealResponse,
    PatientMealsResponse,
)
from rest_server.response_models import ErrorResponse, SuccessResponse
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
from .router import router



@router.get(path="", response_model=PatientMealsResponse, tags=["Meals"])
async def get_meals_api(
    request: Request,
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    source: Optional[str] = Query(None),
    analyzed: Optional[str] = Query(None, regex="^(true|false|both)$"),
    order_by: Optional[str] = Query("time"),
    order: Optional[str] = Query("desc"),
    current_patient: Patient = Depends(get_current_patient),
    limit: Optional[int] = Query(None),
):
    """
    Get Meals API
    """
    async with request.state.context.postgres_store.get_session() as session:
        try:
            query = (
                select(PatientMeal)
                .where(PatientMeal.patient_id == current_patient.patient_id)
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

            if from_date:
                query = query.filter(PatientMeal.time >= from_date)
            if to_date:
                query = query.filter(PatientMeal.time <= to_date)
            if source:
                query = query.filter(PatientMeal.source == source)
            if analyzed == "true":
                query = query.filter(PatientMeal.analyzed == True)
            elif analyzed == "false":
                query = query.filter(PatientMeal.analyzed == False)

            # Add ordering
            if order_by == "time":
                if order == "asc":
                    query = query.order_by(asc(PatientMeal.time))
                else:
                    query = query.order_by(desc(PatientMeal.time))
            elif order_by == "created_at":
                if order == "asc":
                    query = query.order_by(asc(PatientMeal.uploaded_at))
                else:
                    query = query.order_by(desc(PatientMeal.uploaded_at))

            # Apply limit if provided
            if limit is not None:
                query = query.limit(limit)

            result = await session.execute(query)
            meals = result.scalars().all()

            meals = [PatientMealResponse.from_orm(meal) for meal in meals]

            return PatientMealsResponse(
                message="Meals fetched successfully",
                data=meals,
            )
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
