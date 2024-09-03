from datetime import datetime, date
from typing import Any, List, Optional
from pydantic import BaseModel

from lib.schemas.patient_meal import FoodItem, PatientMeal


class TotalNutritionStats(BaseModel):
    calories: float
    proteins: float
    carbohydrates: float
    fats: float
    fiber: float

    calcium: float
    iron: float
    zinc: float
    magnesium: float
    cholesterol: float


class MealDailyStats(TotalNutritionStats):
    date: date
    meal_count: Optional[int] = None
    meals: Any
    avg_glucose: float

    class Config:
        orm_mode = True


class MealWeeklyStats(BaseModel):
    week_number: int
    from_date: datetime
    to_date: datetime
    calories: float
    proteins: float
    carbohydrates: float
    fats: float
    fiber: float
    daily_stats: List[MealDailyStats]

    class Config:
        orm_mode = True


class MealMonthlyStats(BaseModel):
    month: str
    from_date: datetime
    to_date: datetime
    calories: float
    proteins: float
    carbohydrates: float
    fats: float
    fiber: float
    daily_stats: List[MealDailyStats]
    weekly_stats: List[MealWeeklyStats]

    class Config:
        orm_mode = True


class MealSummaryStats(BaseModel):
    from_date: datetime
    to_date: datetime
    calories: float
    proteins: float
    carbohydrates: float
    fats: float
    fiber: float

    class Config:
        orm_mode = True
