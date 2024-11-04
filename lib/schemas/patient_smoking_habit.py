import uuid
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientSmokingHabitBase(BaseModel):
    smoke_status: bool
    years_of_smoking: Optional[int] = None
    cigarettes_per_day: Optional[int] = None
    quit_years_ago: Optional[int] = None


class PatientSmokingHabitCreate(PatientSmokingHabitBase):
    pass


class PatientSmokingHabit(PatientSmokingHabitBase):
    id: UUID
    patient_id: UUID

    class Config:
        from_attributes = True
