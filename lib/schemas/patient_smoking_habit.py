from datetime import datetime
from typing import Optional
import uuid
from pydantic import BaseModel
from uuid import UUID
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientSmokingHabitBase(BaseModel):
    smoke_status: str
    years_of_smoking: Optional[int] = None
    cigarettes_per_day: Optional[int] = None
    quit_years_ago: Optional[int] = None


class PatientSmokingHabitCreate(PatientSmokingHabitBase):
    pass


class PatientSmokingHabit(PatientSmokingHabitBase):
    id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True
