import uuid
from datetime import datetime
from datetime import time as datetime_time
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientSleepHabitBase(BaseModel):
    sleep_quality: str
    wake_up_fresh: Optional[bool] = None
    drowsy_day: Optional[bool] = None
    average_sleep_duration: Optional[str] = None
    wake_up_time: Optional[datetime_time] = None
    bed_time: Optional[datetime_time] = None


class PatientSleepHabitCreate(PatientSleepHabitBase):
    pass


class PatientSleepHabit(PatientSleepHabitBase):
    patient_id: UUID

    class Config:
        from_attributes = True
