from datetime import date, datetime
from typing import Any, List, Optional

from pydantic import BaseModel

from lib.schemas.patient_meal import PatientFoodItem, PatientMeal


class NutritionStats(BaseModel):
    calories: float
    proteins: float
    carbohydrates: float
    fats: float
    fiber: float

    calcium: float
    iron: float
    zinc: float
    magnesium: float


class DailyMealStats(NutritionStats):
    date: date
    meal_count: Optional[int] = None
    meals: Any
    avg_glucose: float

    class Config:
        from_attributes = True


class WeeklyMealStats(NutritionStats):
    week_number: int
    from_date: datetime
    to_date: datetime
    daily_stats: List[DailyMealStats]

    class Config:
        from_attributes = True


class MonthlyMealStats(NutritionStats):
    month: str
    from_date: datetime
    to_date: datetime
    daily_stats: List[DailyMealStats]
    weekly_stats: List[WeeklyMealStats]

    class Config:
        from_attributes = True


class MealSummaryStats(NutritionStats):
    from_date: datetime
    to_date: datetime

    class Config:
        from_attributes = True
