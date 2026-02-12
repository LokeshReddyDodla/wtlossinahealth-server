from datetime import datetime, date as datetime_date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class MealDistribution(BaseModel):
    calories: float
    carbs: float
    protein: float
    fats: float
    fiber: float
    calcium: float
    iron: float
    zinc: float
    magnesium: float


class PatientDietPlanBase(MealDistribution):
    major_meal: Optional[MealDistribution] = None
    snack: Optional[MealDistribution] = None


class PatientDietPlanCreate(PatientDietPlanBase):
    start_date: datetime_date
    end_date: Optional[datetime_date] = None
    is_default: bool = False
    status: str = "ACTIVE"
    plan_reason: Optional[str] = None


class PatientDietPlanUpdate(PatientDietPlanBase):
    start_date: datetime_date
    end_date: Optional[datetime_date] = None
    is_default: bool = False
    status: str = "ACTIVE"
    plan_reason: Optional[str] = None
    pass


class PatientDietPlan(PatientDietPlanBase):
    diet_plan_id: UUID
    patient_id: UUID
    start_date: datetime_date
    end_date: Optional[datetime_date] = None
    is_default: bool = False
    status: str = "ACTIVE"
    plan_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
