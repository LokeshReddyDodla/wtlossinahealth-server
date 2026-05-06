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
from lib.models.associations import patient_care_provider_association


def build_condition(column, threshold, op: Optional[str]):
    if threshold is None or op is None:
        return None
    op_map = {
        "lt": column < threshold,
        "lte": column <= threshold,
        "gt": column > threshold,
        "gte": column >= threshold,
        "eq": column == threshold,
    }
    return op_map.get(op)


class MealMetricsService:
    async def get_meal_uploads_grouped_by_date(
        self,
        health_facility_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        is_facility_admin: bool = False,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        with_photos_only: bool = False,
    ) -> list[dict]:
        try:
            async with get_async_postgres_session() as session:
                stmt = select(
                    cast(PatientMealModel.uploaded_at, Date).label("date"),
                    func.count().label("count"),
                ).join(
                    PatientModel,
                    PatientMealModel.patient_id == PatientModel.patient_id,
                )

                stmt = self._apply_patient_scope_filters(
                    stmt,
                    health_facility_id=health_facility_id,
                    care_provider_id=care_provider_id,
                    is_facility_admin=is_facility_admin,
                )

                if start:
                    stmt = stmt.where(PatientMealModel.uploaded_at >= start)
                if end:
                    stmt = stmt.where(PatientMealModel.uploaded_at <= end)
                if with_photos_only:
                    stmt = stmt.where(PatientMealModel.image_url.isnot(None))

                stmt = stmt.group_by(
                    cast(PatientMealModel.uploaded_at, Date)
                ).order_by("date")

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

    async def get_macro_filtered_major_meals(
        self,
        health_facility_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        is_facility_admin: bool = False,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        protein_threshold: Optional[float] = None,
        protein_op: Optional[str] = None,
        fiber_threshold: Optional[float] = None,
        fiber_op: Optional[str] = None,
        carbs_threshold: Optional[float] = None,
        carbs_op: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PatientMealModel]:
        major_meals = ["breakfast", "lunch", "dinner"]

        try:
            async with get_async_postgres_session() as session:
                stmt = (
                    select(PatientMealModel)
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
                        selectinload(PatientMealModel.patient).selectinload(
                            PatientModel.diabetic_history
                        ),
                    )
                    .where(PatientMealModel.type.in_(major_meals))
                    .order_by(PatientMealModel.uploaded_at.desc())
                    .offset(offset)
                    .limit(limit)
                )

                stmt = self._apply_patient_scope_filters(
                    stmt,
                    health_facility_id=health_facility_id,
                    care_provider_id=care_provider_id,
                    is_facility_admin=is_facility_admin,
                )

                if start:
                    stmt = stmt.where(PatientMealModel.uploaded_at >= start)
                if end:
                    stmt = stmt.where(PatientMealModel.uploaded_at <= end)

                for condition in [
                    build_condition(
                        PatientTotalMacroNutritionalValueModel.proteins,
                        protein_threshold,
                        protein_op,
                    ),
                    build_condition(
                        PatientTotalMacroNutritionalValueModel.fiber,
                        fiber_threshold,
                        fiber_op,
                    ),
                    build_condition(
                        PatientTotalMacroNutritionalValueModel.carbohydrates,
                        carbs_threshold,
                        carbs_op,
                    ),
                ]:
                    if condition is not None:
                        stmt = stmt.where(condition)

                result = await session.execute(stmt)
                meals = result.unique().scalars().all()

                return list(meals)

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch macro filtered meals",
                detail=str(e),
            )

    def _apply_patient_scope_filters(
        self,
        stmt,
        *,
        health_facility_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        is_facility_admin: bool = False,
    ):
        if health_facility_id and is_facility_admin:
            return stmt.where(
                PatientMealModel.patient_id.in_(
                    select(PatientModel.patient_id).where(
                        PatientModel.health_facility_id == health_facility_id
                    )
                )
            )

        if care_provider_id:
            stmt = stmt.where(
                PatientMealModel.patient_id.in_(
                    select(
                        patient_care_provider_association.c.patient_id
                    ).where(
                        patient_care_provider_association.c.care_provider_id
                        == care_provider_id
                    )
                )
            )

        return stmt
