from typing import Optional
from sqlalchemy import select, func, cast, Date
from sqlalchemy.exc import SQLAlchemyError
from lib.dependencies.database import get_async_postgres_session
from lib.models.patient_meal import PatientMeal as PatientMealModel
from lib.utils.http_exceptions import raise_http_exception
from sqlalchemy.orm import selectinload
from lib.models.patient import Patient as PatientModel
from starlette import status
from uuid import UUID
from datetime import datetime
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


class MealMetricsService:
    async def get_meal_uploads_grouped_by_date(
        self,
        health_facility_id: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[dict]:
        try:
            async with get_async_postgres_session() as session:
                stmt = (
                    select(
                        cast(PatientMealModel.uploaded_at, Date).label("date"),
                        func.count().label("count"),
                    )
                    .join(
                        PatientModel,
                        PatientModel.patient_id == PatientMealModel.patient_id,
                    )
                    .where(
                        PatientModel.health_facility_id == health_facility_id
                    )
                    .group_by(cast(PatientMealModel.uploaded_at, Date))
                    .order_by("date")
                )

                if start:
                    stmt = stmt.where(PatientMealModel.uploaded_at >= start)
                if end:
                    stmt = stmt.where(PatientMealModel.uploaded_at <= end)

                result = await session.execute(stmt)
                rows = result.all()

                return [
                    {"date": row.date.isoformat(), "count": row.count}
                    for row in rows
                ]

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch meal uploads",
                detail=str(e),
            )

    async def get_high_carb_meals(
        self,
        health_facility_id: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        carb_threshold: float = 50.0,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        major_meals = ["breakfast", "lunch", "dinner"]

        try:
            async with get_async_postgres_session() as session:
                stmt = (
                    select(PatientMealModel)
                    .join(
                        PatientModel,
                        PatientMealModel.patient_id == PatientModel.patient_id,
                    )
                    .join(
                        PatientTotalMacroNutritionalValueModel,
                        PatientMealModel.id
                        == PatientTotalMacroNutritionalValueModel.meal_id,
                    )
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
                        selectinload(PatientMealModel.patient),
                    )
                    .where(
                        PatientModel.health_facility_id == health_facility_id,
                        PatientTotalMacroNutritionalValueModel.carbohydrates
                        > carb_threshold,
                        PatientMealModel.type.in_(major_meals),
                    )
                    .order_by(PatientMealModel.uploaded_at.desc())
                    .offset(offset)
                    .limit(limit)
                )

                if start:
                    stmt = stmt.where(PatientMealModel.uploaded_at >= start)
                if end:
                    stmt = stmt.where(PatientMealModel.uploaded_at <= end)

                result = await session.execute(stmt)
                meals = result.scalars().all()

                return list(meals)

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch full high-carb meals",
                detail=str(e),
            )

    async def get_low_protein_fiber_major_meals(
        self,
        health_facility_id: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        protein_threshold: float = 20.0,
        fiber_threshold: float = 10.0,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PatientMealModel]:
        major_meals = ["breakfast", "lunch", "dinner"]

        try:
            async with get_async_postgres_session() as session:
                stmt = (
                    select(PatientMealModel)
                    .join(
                        PatientModel,
                        PatientMealModel.patient_id == PatientModel.patient_id,
                    )
                    .join(
                        PatientTotalMacroNutritionalValueModel,
                        PatientMealModel.id
                        == PatientTotalMacroNutritionalValueModel.meal_id,
                    )
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
                        selectinload(PatientMealModel.patient),
                    )
                    .where(
                        PatientModel.health_facility_id == health_facility_id,
                        PatientTotalMacroNutritionalValueModel.proteins
                        < protein_threshold,
                        PatientTotalMacroNutritionalValueModel.fiber
                        < fiber_threshold,
                        PatientMealModel.type.in_(major_meals),
                    )
                    .order_by(PatientMealModel.uploaded_at.desc())
                    .offset(offset)
                    .limit(limit)
                )

                if start:
                    stmt = stmt.where(PatientMealModel.uploaded_at >= start)
                if end:
                    stmt = stmt.where(PatientMealModel.uploaded_at <= end)

                result = await session.execute(stmt)
                meals = result.scalars().all()

                return list(meals)

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch low protein and fiber major meals",
                detail=str(e),
            )
