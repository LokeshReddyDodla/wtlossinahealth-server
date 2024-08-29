from datetime import datetime
from typing import Optional
import uuid
from pydantic import BaseModel
from uuid import UUID
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientSleepHabitBase(BaseModel):
    sleep_quality: str
    wake_up_fresh: bool
    drowsy_day: bool
    average_sleep_duration: Optional[float] = None
    wake_up_time: Optional[datetime] = None
    bed_time: Optional[datetime] = None


class PatientSleepHabitCreate(PatientSleepHabitBase):
    pass


class PatientSleepHabit(PatientSleepHabitBase):
    patient_id: UUID

    class Config:
        orm_mode = True
