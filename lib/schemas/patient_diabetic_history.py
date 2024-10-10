import uuid
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import relationship

from lib.models import Base


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
        from_attributes = True
