"""Pydantic schemas for meal statistics reports."""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DateRange(BaseModel):
    start: str = Field(..., description="Start date in ISO format")
    end: str = Field(..., description="End date in ISO format")


class ReportMetadata(BaseModel):
    date_range: DateRange
    total_meals: int
    days_covered: int


class MealCounts(BaseModel):
    total_meals: int
    high_carb_meals: int
    low_protein_meals: int
    low_fiber_meals: int


class WithinBudgetPercentages(BaseModel):
    carbs: float
    protein: float
    fat: float
    fiber: float


class NutrientStats(BaseModel):
    median: float
    range: List[float]
    max_value: float
    max_date: date


class MealTypeNutrientStats(BaseModel):
    carbs: Optional[NutrientStats] = None
    proteins: Optional[NutrientStats] = None
    fats: Optional[NutrientStats] = None
    fiber: Optional[NutrientStats] = None


class MealTypeBreakdown(BaseModel):
    by_meal_type: Dict[str, MealTypeNutrientStats]


class MealStatisticsSummary(BaseModel):
    counts: MealCounts
    within_budget_percentages: WithinBudgetPercentages


class DailyMeals(BaseModel):
    """Meals for a specific date."""
    date: str = Field(..., description="Date in ISO format")
    meals: List[Dict[str, Any]] = Field(..., description="List of meals for this date")


class MealsData(BaseModel):
    """Meals data organized by date."""
    by_date: List[DailyMeals] = Field(..., description="Meals grouped by date")


class MealStatisticsReport(BaseModel):
    metadata: ReportMetadata
    summary: MealStatisticsSummary
    breakdowns: MealTypeBreakdown
    meals: Optional[MealsData] = Field(None, description="Meal data organized by date")


class WeeklyPeriod(BaseModel):
    week_label: str
    iso_week_no: str
    start_date: str
    end_date: str


class WeeklyEnergyDistribution(BaseModel):
    carbs: float
    protein: float
    fat: float


class WeeklySummary(BaseModel):
    period: WeeklyPeriod
    median_carbs: float
    energy_distribution: WeeklyEnergyDistribution


class MealTypeMedians(BaseModel):
    carbs: float
    protein: float
    fat: float
    fiber: float


class MealTypeComparison(BaseModel):
    current: MealTypeMedians
    previous: MealTypeMedians


class MonthlyMealCounts(BaseModel):
    total_meals: int
    snacks: int
    breakfast: int
    lunch: int
    dinner: int
    high_carb_meals: int
    low_protein_meals: int


class MonthlySummary(BaseModel):
    counts: MonthlyMealCounts
    within_budget_percentages: WithinBudgetPercentages
    weekly_summaries: List[WeeklySummary]
    meal_type_comparison: Dict[str, MealTypeComparison]
