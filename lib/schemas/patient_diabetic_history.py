from typing import Optional
import uuid
from pydantic import BaseModel
from sqlalchemy import UUID, Column, ForeignKey, String
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientDiabeticHistoryBase(BaseModel):
    type_of_diabetes: Optional[str] = None
    years_with_diabetes: Optional[int] = None
    is_pregnant: Optional[bool] = None
    pregnancy_weeks: Optional[int] = None


class PatientDiabeticHistoryCreate(PatientDiabeticHistoryBase):
    pass


class PatientDiabeticHistory(PatientDiabeticHistoryBase):
    patient_id: UUID

    class Config:
        orm_mode = True
