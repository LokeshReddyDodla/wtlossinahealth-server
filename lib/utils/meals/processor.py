from datetime import date, datetime

from dateutil.parser import parse as parse_date
from sqlalchemy import func
from sqlalchemy.future import select
from sqlalchemy.orm import aliased

from lib.core.postgres_store import PostgresStore
from lib.models.patient_meal import (
    PatientFoodItem,
    PatientMacroNutritionalValue,
    PatientMeal,
    PatientMicroNutritionalValue,
    PatientTotalMacroNutritionalValue,
    PatientTotalMicroNutritionalValue,
)
from lib.schemas.meal_stats import DailyMealStats
from lib.schemas.patient_diet_plan import MealDistribution, PatientDietPlanBase
from lib.utils.diet_plan_calculator import DietPlanCalculator
from lib.utils.cgm.summary import CGMSummaryStatsFetcher
from lib.utils.postgres_session_decorator import with_postgres_session


class MealStatsProcessor:
    def __init__(
        self,
        postgres_store: PostgresStore,
        clickhouse_store,
        cgm_stats_processor,
        patient_profile_service,
        patient_plan_service,
    ):
        self.postgres_store = postgres_store
        self.clickhouse_store = clickhouse_store
        self.patient_profile_service = patient_profile_service
        self.patient_plan_service = patient_plan_service
        self.cgm_stats_processor = cgm_stats_processor

    @with_postgres_session
    async def get_meal_report_by_date(
        self, patient_id: str, date: date, *, postgres_session
    ):
        diet_recommendations = await self.get_diet_recommendations(
            patient_id, date
        )

        # Fetch average glucose for the single date
        avg_glucose = CGMSummaryStatsFetcher.fetch_daily_average_glucose(
            self.clickhouse_store, patient_id, date, date
        ).get(date, 0.0)

        query = self._build_meal_query(patient_id, date, date)
        result = await postgres_session.execute(query)
        row = result.first()

        if not row:
            return self._empty_daily_stats(
                date, {date: avg_glucose}, diet_recommendations
            )

        return self._build_daily_stats(
            row, {date: avg_glucose}, diet_recommendations, patient_id
        )

    @with_postgres_session
    async def get_meal_report_by_date_range(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        *,
        postgres_session
    ):
        diet_recommendations = await self.get_diet_recommendations(
            patient_id, start_date
        )

        # Fetch all glucose stats once for the entire date range
        avg_glucose_by_date = (
            CGMSummaryStatsFetcher.fetch_daily_average_glucose(
                self.clickhouse_store, patient_id, start_date, end_date
            )
        )

        query = self._build_meal_query(patient_id, start_date, end_date)
        result = await postgres_session.execute(query)
        rows = result.all()

        if not rows:
            return [
                self._empty_daily_stats(
                    start_date, avg_glucose_by_date, diet_recommendations
                )
            ]

        return [
            self._build_daily_stats(
                row, avg_glucose_by_date, diet_recommendations, patient_id
            )
            for row in rows
        ]

    def _build_meal_query(
        self, patient_id: str, start_date: date, end_date: date
    ):
        PatientFoodItemAlias = aliased(PatientFoodItem)
        PatientMacroNutritionalValueAlias = aliased(
            PatientMacroNutritionalValue
        )
        PatientMicroNutritionalValueAlias = aliased(
            PatientMicroNutritionalValue
        )

        return (
            select(
                PatientMeal.date,
                func.count(PatientMeal.id).label("meal_count"),
                *self._build_nutritional_aggregates(PatientMeal),
                self._build_meal_json(
                    PatientMeal,
                    PatientFoodItemAlias,
                    PatientMacroNutritionalValueAlias,
                    PatientMicroNutritionalValueAlias,
                )
            )
            .outerjoin(
                PatientTotalMacroNutritionalValue,
                PatientMeal.total_macro_nutritional_value,
            )
            .outerjoin(
                PatientTotalMicroNutritionalValue,
                PatientMeal.total_micro_nutritional_value,
            )
            .where(
                PatientMeal.patient_id == patient_id,
                PatientMeal.date >= start_date,
                PatientMeal.date <= end_date,
            )
            .group_by(PatientMeal.date)
            .order_by(PatientMeal.date)
        )

    def _empty_daily_stats(
        self, date, avg_glucose_by_date, diet_recommendations
    ):
        return DailyMealStats(
            date=date,
            meal_count=0,
            meals=[],
            calories=0,
            proteins=0,
            carbohydrates=0,
            fats=0,
            fiber=0,
            calcium=0,
            iron=0,
            zinc=0,
            magnesium=0,
            avg_glucose=avg_glucose_by_date.get(date, 0.0),
            diet_recommendations=diet_recommendations,
        )

    def _build_nutritional_aggregates(self, meal):
        """Helper function to build aggregate functions for nutritional values."""
        return [
            func.sum(PatientTotalMacroNutritionalValue.calories).label(
                "total_calories"
            ),
            func.sum(PatientTotalMacroNutritionalValue.proteins).label(
                "total_proteins"
            ),
            func.sum(PatientTotalMacroNutritionalValue.carbohydrates).label(
                "total_carbohydrates"
            ),
            func.sum(PatientTotalMacroNutritionalValue.fats).label(
                "total_fats"
            ),
            func.sum(PatientTotalMacroNutritionalValue.fiber).label(
                "total_fiber"
            ),
            func.sum(PatientTotalMicroNutritionalValue.calcium).label(
                "total_calcium"
            ),
            func.sum(PatientTotalMicroNutritionalValue.iron).label(
                "total_iron"
            ),
            func.sum(PatientTotalMicroNutritionalValue.zinc).label(
                "total_zinc"
            ),
            func.sum(PatientTotalMicroNutritionalValue.magnesium).label(
                "total_magnesium"
            ),
        ]

    def _build_meal_json(
        self, meal, food_item_alias, macro_alias, micro_alias
    ):
        """Helper function to build JSON aggregation for meals."""
        return func.json_agg(
            func.json_build_object(
                "id",
                meal.id,
                "name",
                meal.name,
                "type",
                meal.type,
                "date",
                meal.date,
                "time",
                meal.time,
                "description",
                meal.description,
                "source",
                meal.source,
                "tags",
                meal.tags,
                "score",
                meal.score,
                "feedback",
                meal.feedback,
                "image_url",
                meal.image_url,
                "analyzed",
                meal.analyzed,
                "analyzed_at",
                meal.analyzed_at,
                "uploaded_at",
                meal.uploaded_at,
                "total_macro_nutritional_value",
                self._build_macro_json(PatientTotalMacroNutritionalValue),
                "total_micro_nutritional_value",
                self._build_micro_json(PatientTotalMicroNutritionalValue),
                "items",
                self._build_items_json(
                    food_item_alias, macro_alias, micro_alias, meal
                ),
            )
        ).label("meals")

    def _build_macro_json(self, macro):
        """Helper function to build JSON for macro nutritional values."""
        return func.json_build_object(
            "calories",
            macro.calories,
            "proteins",
            macro.proteins,
            "carbohydrates",
            macro.carbohydrates,
            "fats",
            macro.fats,
            "fiber",
            macro.fiber,
        )

    def _build_micro_json(self, micro):
        """Helper function to build JSON for micro nutritional values."""
        return func.json_build_object(
            "calcium",
            micro.calcium,
            "iron",
            micro.iron,
            "zinc",
            micro.zinc,
            "magnesium",
            micro.magnesium,
        )

    def _build_items_json(
        self, food_item_alias, macro_alias, micro_alias, meal
    ):
        """Helper function to build JSON aggregation for meal items."""
        return (
            select(
                func.json_agg(
                    func.json_build_object(
                        "id",
                        food_item_alias.id,
                        "name",
                        food_item_alias.name,
                        "coordinates",
                        food_item_alias.coordinates,
                        "serving_size",
                        food_item_alias.serving_size,
                        "serving_quantity",
                        food_item_alias.serving_quantity,
                        "serving_unit",
                        food_item_alias.serving_unit,
                        "macro_nutritional_values",
                        self._build_macro_json(macro_alias),
                        "micro_nutritional_values",
                        self._build_micro_json(micro_alias),
                    )
                )
            )
            .select_from(food_item_alias)
            .outerjoin(macro_alias, food_item_alias.macro_nutritional_values)
            .outerjoin(micro_alias, food_item_alias.micro_nutritional_values)
            .where(food_item_alias.meal_id == meal.id)
            .correlate(meal)
            .as_scalar()
        )

    async def get_diet_recommendations(
        self, patient_id: str, query_date: date
    ) -> PatientDietPlanBase:
        """Fetch diet recommendations from an active plan or calculate dynamically."""
        active_plan = await self.patient_plan_service.get_active_patient_plan(
            patient_id, query_date
        )

        if active_plan and active_plan.diet_plan:
            return PatientDietPlanBase(
                total_calories=active_plan.diet_plan.total_calories,
                protein=active_plan.diet_plan.protein,
                carbs=active_plan.diet_plan.carbs,
                fats=active_plan.diet_plan.fats,
                fiber=active_plan.diet_plan.fiber,
                calcium=active_plan.calcium,
                iron=active_plan.iron,
                zinc=active_plan.zinc,
                magnesium=active_plan.magnesium,
                major_meal=(
                    MealDistribution(**active_plan.diet_plan.major_meal)
                    if active_plan.diet_plan.major_meal
                    else None
                ),
                snack=(
                    MealDistribution(**active_plan.diet_plan.snack)
                    if active_plan.diet_plan.snack
                    else None
                ),
            )
        else:
            return await self._calculate_recommendations(patient_id)

    async def _calculate_recommendations(
        self,
        patient_id: str,
    ):
        """Calculate recommendations dynamically if no active plan exists."""
        patient = await self.patient_profile_service.fetch_patient_profile(
            patient_id, detailed=True
        )

        if (
            patient.weight is None
            or patient.height is None
            or patient.dob is None
            or patient.gender is None
        ):
            # Return default values if the profile is incomplete
            return PatientDietPlanBase(
                total_calories=0,
                protein=0,
                carbs=0,
                fats=0,
                fiber=0,
                calcium=0,
                iron=0,
                zinc=0,
                magnesium=0,
                major_meal=MealDistribution(
                    total_calories=0,
                    protein=0,
                    carbs=0,
                    fats=0,
                    fiber=0,
                    calcium=0,
                    iron=0,
                    zinc=0,
                    magnesium=0,
                ),
                snack=MealDistribution(
                    total_calories=0,
                    protein=0,
                    carbs=0,
                    fats=0,
                    fiber=0,
                    calcium=0,
                    iron=0,
                    zinc=0,
                    magnesium=0,
                ),
            )

        # age = calculate_age(patient.dob)
        age = 24
        calculator = DietPlanCalculator(
            weight=patient.weight,
            height=patient.height,
            age=age,
            gender=patient.gender,
            activity_level=(
                patient.daily_activity.activity_level
                if patient.daily_activity
                else "sedentary"
            ),
        )

        tdee = calculator.calculate_tdee()
        macronutrients = calculator.calculate_macronutrients(tdee)
        micronutrients = calculator.get_micronutrient_recommendations()

        meals_per_day = getattr(patient.eating_habit, "meals_per_day", 3) or 3
        snacks_count = getattr(patient.eating_habit, "snacks_count", 2) or 2

        # Calculate the ratio for major meals and snacks based on their count
        total_meal_count = meals_per_day + snacks_count
        major_meal_ratio = meals_per_day / total_meal_count
        snack_ratio = snacks_count / total_meal_count

        # Calculate per-meal recommendations for major meals
        major_meal_distribution = MealDistribution(
            total_calories=(tdee * major_meal_ratio) / meals_per_day,
            protein=(macronutrients["protein"] * major_meal_ratio)
            / meals_per_day,
            carbs=(macronutrients["carbs"] * major_meal_ratio) / meals_per_day,
            fats=(macronutrients["fats"] * major_meal_ratio) / meals_per_day,
            fiber=(micronutrients["fiber"] * major_meal_ratio) / meals_per_day,
            calcium=(micronutrients["calcium"] * major_meal_ratio)
            / meals_per_day,
            iron=(micronutrients["iron"] * major_meal_ratio) / meals_per_day,
            zinc=(micronutrients["zinc"] * major_meal_ratio) / meals_per_day,
            magnesium=(micronutrients["magnesium"] * major_meal_ratio)
            / meals_per_day,
        )

        # Calculate per-snack recommendations for snacks
        snack_distribution = MealDistribution(
            total_calories=(tdee * snack_ratio) / snacks_count,
            protein=(macronutrients["protein"] * snack_ratio) / snacks_count,
            carbs=(macronutrients["carbs"] * snack_ratio) / snacks_count,
            fats=(macronutrients["fats"] * snack_ratio) / snacks_count,
            fiber=(micronutrients["fiber"] * snack_ratio) / snacks_count,
            calcium=(micronutrients["calcium"] * snack_ratio) / snacks_count,
            iron=(micronutrients["iron"] * snack_ratio) / snacks_count,
            zinc=(micronutrients["zinc"] * snack_ratio) / snacks_count,
            magnesium=(micronutrients["magnesium"] * snack_ratio)
            / snacks_count,
        )

        return PatientDietPlanBase(
            total_calories=tdee,
            protein=macronutrients["protein"],
            carbs=macronutrients["carbs"],
            fats=macronutrients["fats"],
            fiber=micronutrients["fiber"],
            calcium=micronutrients["calcium"],
            iron=micronutrients["iron"],
            zinc=micronutrients["zinc"],
            magnesium=micronutrients["magnesium"],
            major_meal=major_meal_distribution,
            snack=snack_distribution,
        )

    def _build_daily_stats(
        self, row, avg_glucose_by_date, diet_recommendations, patient_id: str
    ):
        """Helper function to build MealDailyStats from a query row."""

        for meal in row.meals:
            meal_time = datetime.combine(
                row.date, parse_date(meal["time"]).time()
            )
            glucose_before_meal, glucose_after_meal = (
                self.cgm_stats_processor.fetch_glucose_around_meal(
                    patient_id, meal_time
                )
            )

            # Append glucose readings to each meal
            meal["glucose_before_meal"] = glucose_before_meal
            meal["glucose_after_meal"] = glucose_after_meal

        return DailyMealStats(
            date=row.date,
            meal_count=row.meal_count,
            meals=row.meals,
            calories=row.total_calories or 0,
            proteins=row.total_proteins or 0,
            carbohydrates=row.total_carbohydrates or 0,
            fats=row.total_fats or 0,
            fiber=row.total_fiber or 0,
            calcium=row.total_calcium or 0,
            iron=row.total_iron or 0,
            zinc=row.total_zinc or 0,
            magnesium=row.total_magnesium or 0,
            avg_glucose=avg_glucose_by_date.get(row.date, 0.0),
            diet_recommendations=diet_recommendations,
        )
