from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PatientDietPlanBase(BaseModel):
    total_calories: float
    carbs: float
    protein: float
    fats: float
    fiber: float


class PatientDietPlanCreate(PatientDietPlanBase):
    pass


class PatientDietPlan(PatientDietPlanBase):
    diet_plan_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
