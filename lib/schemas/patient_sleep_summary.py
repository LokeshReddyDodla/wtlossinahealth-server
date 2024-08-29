from datetime import datetime
from typing import Optional
import uuid
from pydantic import BaseModel
from sqlalchemy import UUID, Column, ForeignKey, String
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientSleepSummaryBase(BaseModel):
    sleep_quality: str
    wake_up_fresh: bool
    drowsy_day: bool
    average_sleep_duration: Optional[float] = None
    wake_up_time: Optional[datetime] = None
    bed_time: Optional[datetime] = None


class PatientSleepSummaryCreate(PatientSleepSummaryBase):
    pass


class PatientSleepSummary(PatientSleepSummaryBase):
    patient_id: UUID

    class Config:
        orm_mode = True
