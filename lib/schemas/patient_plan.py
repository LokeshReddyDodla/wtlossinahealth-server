from datetime import date as datetime_date
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PatientPlanBase(BaseModel):
    patient_id: UUID
    diet_plan_id: Optional[UUID] = None
    fitness_plan_id: Optional[UUID] = None
    start_date: datetime_date
    end_date: Optional[datetime_date] = None


class PatientPlan(PatientPlanBase):
    plan_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
