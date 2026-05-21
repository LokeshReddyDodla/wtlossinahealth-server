import uuid
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientDailyActivityBase(BaseModel):
    activity_level: Optional[str] = None


class PatientDailyActivityCreate(PatientDailyActivityBase):
    pass


class PatientDailyActivity(PatientDailyActivityBase):
    id: UUID
    patient_id: UUID

    class Config:
        from_attributes = True
