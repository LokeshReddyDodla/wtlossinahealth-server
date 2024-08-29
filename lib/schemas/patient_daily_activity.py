import uuid
from pydantic import BaseModel
from sqlalchemy import UUID, Column, ForeignKey, String
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientDailyActivityBase(BaseModel):
    activity_level: str


class PatientDailyActivityCreate(PatientDailyActivityBase):
    pass


class PatientDailyActivity(PatientDailyActivityBase):
    id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True
