from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PatientFitnessPlanBase(BaseModel):
    steps_goal: float
    workout_plan: str


class PatientFitnessPlanCreate(PatientFitnessPlanBase):
    pass


class PatientFitnessPlan(PatientFitnessPlanBase):
    fitness_plan_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
