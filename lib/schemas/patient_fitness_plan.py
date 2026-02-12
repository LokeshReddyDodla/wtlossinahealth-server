from datetime import datetime, date as datetime_date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PatientFitnessPlanBase(BaseModel):
    start_date: datetime_date
    end_date: Optional[datetime_date] = None
    is_default: bool = False
    status: str = "ACTIVE"
    plan_reason: Optional[str] = None

    steps_goal: float
    workout_plan: str


class PatientFitnessPlanCreate(PatientFitnessPlanBase):
    pass

class PatientFitnessPlanUpdate(PatientFitnessPlanBase):
    pass


class PatientFitnessPlan(PatientFitnessPlanBase):
    fitness_plan_id: UUID
    patient_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
